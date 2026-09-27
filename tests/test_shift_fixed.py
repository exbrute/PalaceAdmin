from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bot.config import Settings
from bot.langame_api import WorkingShift
from bot.ledger import compute_open_shift_stats, recalculate_club_shift_group, sync_admin_shifts
from bot.shift_fixed import club_shift_key, distribute_club_shift_fixed, first_opener_id
from bot.storage import Storage, UserLink

TZ = ZoneInfo("Europe/Moscow")


def settings(path: Path) -> Settings:
    return Settings(
        telegram_bot_token="123456:TEST-TOKEN",
        langame_api_url="http://langame.invalid",
        langame_api_token="x",
        fixed_salary=2500,
        fixed_shift_work=2000,
        fixed_cleaning=500,
        shift_standard_hours=12,
        bar_bonus_percent=20,
        database_path=path,
        manager_telegram_ids=frozenset(),
        developer_telegram_ids=frozenset(),
        settlement_timezone="Europe/Moscow",
        earnings_start_date=None,
    )


def shift(
    shift_id: int,
    user_id: int,
    start: datetime,
    stop: datetime | None,
    *,
    club_id: int = 1,
) -> WorkingShift:
    return WorkingShift(
        id=shift_id,
        user_id=user_id,
        club_id=club_id,
        date_start=start,
        date_stop=stop,
    )


class FakeLangame:
    def __init__(self, shifts: list[WorkingShift]) -> None:
        self.shifts = shifts
        self.sales_calls = 0

    def get_working_shifts(self) -> list[WorkingShift]:
        return self.shifts

    def get_product_sales(self, date_from=None, date_to=None):
        self.sales_calls += 1
        return []


class CleaningAssignmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = settings(Path(self.tmp.name) / "bot.db")
        self.storage = Storage(self.settings.database_path)

    def tearDown(self) -> None:
        self.storage.close()
        self.tmp.cleanup()

    def test_both_linked_earlier_opener_gets_cleaning(self) -> None:
        earlier = shift(
            100,
            10,
            datetime(2026, 9, 21, 12, 0, tzinfo=TZ),
            datetime(2026, 9, 22, 0, 0, tzinfo=TZ),
        )
        later = shift(
            464,
            20,
            datetime(2026, 9, 21, 21, 35, tzinfo=TZ),
            datetime(2026, 9, 22, 3, 50, tzinfo=TZ),
        )
        self.storage.link_admin(10, 10, "first@club.ru", "Первый")
        self.storage.link_admin(20, 20, "second@club.ru", "Второй")
        key = club_shift_key(later, self.settings)
        self.assertEqual(key, club_shift_key(earlier, self.settings))
        self.assertEqual(first_opener_id([later, earlier], self.settings, key), 100)

        _, error = recalculate_club_shift_group(
            FakeLangame([earlier, later]), self.storage, self.settings, [earlier, later], key
        )
        self.assertIsNone(error)
        first = self.storage.get_shift_earning(100)
        second = self.storage.get_shift_earning(464)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        assert first is not None and second is not None
        self.assertEqual(first.fixed_cleaning, 500)
        self.assertEqual(second.fixed_cleaning, 0)
        self.assertGreater(first.fixed_work, 0)
        self.assertGreater(second.fixed_work, 0)
        self.assertAlmostEqual(first.fixed_work + second.fixed_work, 2000, places=2)

    def test_unlinked_earlier_opener_denies_cleaning_and_keeps_hourly_pool(self) -> None:
        earlier = shift(
            100,
            10,
            datetime(2026, 9, 21, 18, 0, tzinfo=TZ),
            datetime(2026, 9, 21, 21, 30, tzinfo=TZ),
        )
        later = shift(
            464,
            20,
            datetime(2026, 9, 21, 21, 35, tzinfo=TZ),
            datetime(2026, 9, 22, 3, 50, tzinfo=TZ),
        )
        self.storage.link_admin(20, 20, "second@club.ru", "Второй")
        key = club_shift_key(later, self.settings)
        shares = distribute_club_shift_fixed(
            [later],
            self.settings,
            first_opener_id=first_opener_id([earlier, later], self.settings, key),
        )
        self.assertEqual(shares[464].fixed_cleaning, 0)
        self.assertAlmostEqual(shares[464].worked_hours, 6.25)
        self.assertAlmostEqual(shares[464].fixed_work, 1041.67)

        _, error = recalculate_club_shift_group(
            FakeLangame([earlier, later]), self.storage, self.settings, [earlier, later], key
        )
        self.assertIsNone(error)
        earning = self.storage.get_shift_earning(464)
        self.assertIsNotNone(earning)
        assert earning is not None
        self.assertEqual(earning.fixed_cleaning, 0)
        self.assertAlmostEqual(earning.fixed_work, 1041.67)
        self.assertIsNone(self.storage.get_shift_earning(100))

    def test_shift_before_rollover_is_previous_club_day(self) -> None:
        morning = shift(
            90,
            10,
            datetime(2026, 9, 21, 9, 30, tzinfo=TZ),
            datetime(2026, 9, 21, 11, 0, tzinfo=TZ),
        )
        evening = shift(
            464,
            20,
            datetime(2026, 9, 21, 21, 35, tzinfo=TZ),
            datetime(2026, 9, 22, 3, 50, tzinfo=TZ),
        )
        self.assertEqual(club_shift_key(morning, self.settings), "1:2026-09-20")
        self.assertEqual(club_shift_key(evening, self.settings), "1:2026-09-21")
        self.assertEqual(
            first_opener_id([morning, evening], self.settings, "1:2026-09-21"),
            464,
        )

    def test_open_earlier_shift_still_blocks_cleaning(self) -> None:
        earlier = shift(100, 10, datetime(2026, 9, 21, 15, 0, tzinfo=TZ), None)
        later = shift(
            464,
            20,
            datetime(2026, 9, 21, 21, 35, tzinfo=TZ),
            datetime(2026, 9, 22, 3, 50, tzinfo=TZ),
        )
        key = club_shift_key(later, self.settings)
        self.assertEqual(first_opener_id([earlier, later], self.settings, key), 100)

        link = UserLink(20, 20, "second@club.ru", "Второй", "admin")
        self.storage.link_admin(20, 20, "second@club.ru", "Второй")
        stats = compute_open_shift_stats(
            FakeLangame([earlier, later]),
            self.storage,
            self.settings,
            link,
            later,
        )
        self.assertEqual(stats.fixed_share.fixed_cleaning, 0)

    def test_same_start_lower_id_is_opener(self) -> None:
        start = datetime(2026, 9, 21, 21, 35, tzinfo=TZ)
        stop = datetime(2026, 9, 22, 3, 50, tzinfo=TZ)
        low = shift(10, 1, start, stop)
        high = shift(20, 2, start, stop)
        key = club_shift_key(low, self.settings)
        self.assertEqual(first_opener_id([high, low], self.settings, key), 10)
        shares = distribute_club_shift_fixed(
            [high, low], self.settings, first_opener_id=10
        )
        self.assertEqual(shares[10].fixed_cleaning, 500)
        self.assertEqual(shares[20].fixed_cleaning, 0)

    def test_sync_corrects_stored_cleaning_for_second_opener(self) -> None:
        earlier = shift(
            100,
            10,
            datetime(2026, 9, 21, 18, 0, tzinfo=TZ),
            datetime(2026, 9, 21, 21, 30, tzinfo=TZ),
        )
        later = shift(
            464,
            20,
            datetime(2026, 9, 21, 21, 35, tzinfo=TZ),
            datetime(2026, 9, 22, 3, 50, tzinfo=TZ),
        )
        self.storage.link_admin(20, 20, "second@club.ru", "Второй")
        self.storage.add_shift_earning(
            shift_id=464,
            telegram_id=20,
            langame_user_id=20,
            shift_start=later.date_start.isoformat(timespec="seconds"),
            shift_stop=later.date_stop.isoformat(timespec="seconds") if later.date_stop else None,
            bar_sales=490,
            bar_bonus=98,
            fixed_salary=1541.67,
            gross_amount=1639.67,
            sales_count=3,
            worked_hours=6.25,
            fixed_work=1041.67,
            fixed_cleaning=500,
            club_shift_key="1:2026-09-21",
        )
        link = self.storage.get_link(20)
        self.assertIsNotNone(link)
        assert link is not None
        api = FakeLangame([earlier, later])
        synced, error, new_ids = sync_admin_shifts(api, self.storage, self.settings, link)
        self.assertIsNone(error)
        self.assertEqual(synced, 0)
        self.assertEqual(new_ids, [])
        earning = self.storage.get_shift_earning(464)
        self.assertIsNotNone(earning)
        assert earning is not None
        self.assertEqual(earning.fixed_cleaning, 0)
        self.assertAlmostEqual(earning.fixed_work, 1041.67)
        self.assertAlmostEqual(earning.fixed_salary, 1041.67)
        self.assertGreater(api.sales_calls, 0)

    def test_sync_leaves_correct_second_opener_untouched(self) -> None:
        earlier = shift(
            100,
            10,
            datetime(2026, 9, 21, 18, 0, tzinfo=TZ),
            datetime(2026, 9, 21, 21, 30, tzinfo=TZ),
        )
        later = shift(
            464,
            20,
            datetime(2026, 9, 21, 21, 35, tzinfo=TZ),
            datetime(2026, 9, 22, 3, 50, tzinfo=TZ),
        )
        self.storage.link_admin(20, 20, "second@club.ru", "Второй")
        self.storage.add_shift_earning(
            shift_id=464,
            telegram_id=20,
            langame_user_id=20,
            shift_start=later.date_start.isoformat(timespec="seconds"),
            shift_stop=later.date_stop.isoformat(timespec="seconds") if later.date_stop else None,
            bar_sales=999,
            bar_bonus=0,
            fixed_salary=1041.67,
            gross_amount=1041.67,
            sales_count=0,
            worked_hours=6.25,
            fixed_work=1041.67,
            fixed_cleaning=0,
            club_shift_key="1:2026-09-21",
        )
        link = self.storage.get_link(20)
        assert link is not None
        api = FakeLangame([earlier, later])
        sync_admin_shifts(api, self.storage, self.settings, link)
        earning = self.storage.get_shift_earning(464)
        assert earning is not None
        self.assertEqual(earning.bar_sales, 999)
        self.assertEqual(earning.fixed_cleaning, 0)
        self.assertEqual(api.sales_calls, 0)
