from __future__ import annotations

import json
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from aiohttp.test_utils import TestClient, TestServer

from bot.config import Settings
from bot.langame_api import AdminUser, ProductSale, WorkingShift
from bot.pay_period import current_pay_period, today_in_timezone
from bot.storage import Storage
from bot.webapp.auth import InitDataError, sign_init_data, validate_init_data
from bot.webapp.server import create_web_app

TOKEN = "123456:TEST-TOKEN"
DEVELOPER_ID = 1
MANAGER_ID = 2
ADMIN_ID = 3
STRANGER_ID = 99
TZ = ZoneInfo("Europe/Moscow")


def make_init_data(telegram_id: int, *, token: str = TOKEN, auth_date: int | None = None) -> str:
    fields = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAH",
        "user": json.dumps({"id": telegram_id, "first_name": f"User{telegram_id}"}),
    }
    fields["hash"] = sign_init_data(fields, token)
    return urlencode(fields)


class FakeLangame:
    def __init__(self) -> None:
        now = datetime.now(TZ)
        self.users = [
            AdminUser(id=501, email="admin@club.ru", username="Админ Иван"),
            AdminUser(id=502, email="other@club.ru", username="Другой"),
        ]
        self.closed_shift = WorkingShift(
            id=7001,
            user_id=501,
            club_id=1,
            date_start=now - timedelta(hours=14),
            date_stop=now - timedelta(hours=2),
        )
        self.open_shift = WorkingShift(
            id=7002,
            user_id=501,
            club_id=1,
            date_start=now - timedelta(hours=1),
            date_stop=None,
            cash_nal=1000,
            cash_beznal=3000,
        )
        self.shifts = [self.closed_shift]
        self.sales = [
            ProductSale(
                id=9001,
                working_shift_id=7001,
                product_id=1,
                product_name="Кола",
                price_sale=100,
                count=5,
                cancel=0,
                date=now - timedelta(hours=10),
            ),
            ProductSale(
                id=9002,
                working_shift_id=7002,
                product_id=1,
                product_name="Кола",
                price_sale=100,
                count=2,
                cancel=0,
                date=now - timedelta(minutes=30),
            ),
        ]

    def get_users(self):
        return self.users

    def get_working_shifts(self):
        return list(self.shifts)

    def get_product_sales(self, date_from=None, date_to=None):
        return list(self.sales)

    def get_transactions(self, date_from=None, date_to=None):
        return []

    def close(self):
        pass


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []
        self.documents: list[tuple[int, str]] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text))

    async def send_document(self, chat_id, document, filename=None, **kwargs):
        self.documents.append((chat_id, filename))


class InitDataTests(unittest.TestCase):
    def test_valid(self):
        user = validate_init_data(make_init_data(42), TOKEN)
        self.assertEqual(user.telegram_id, 42)
        self.assertEqual(user.first_name, "User42")

    def test_wrong_token(self):
        with self.assertRaises(InitDataError):
            validate_init_data(make_init_data(42, token="other:token"), TOKEN)

    def test_tampered_user(self):
        data = make_init_data(42).replace("42", "43")
        with self.assertRaises(InitDataError):
            validate_init_data(data, TOKEN)

    def test_expired(self):
        old = int(time.time()) - 3 * 24 * 3600
        with self.assertRaises(InitDataError):
            validate_init_data(make_init_data(42, auth_date=old), TOKEN)

    def test_empty(self):
        with self.assertRaises(InitDataError):
            validate_init_data("", TOKEN)


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = Settings(
            telegram_bot_token=TOKEN,
            langame_api_url="http://langame.invalid",
            langame_api_token="x",
            fixed_salary=2500,
            fixed_shift_work=2000,
            fixed_cleaning=500,
            shift_standard_hours=12,
            bar_bonus_percent=20,
            database_path=Path(self.tmp.name) / "bot.db",
            manager_telegram_ids=frozenset({MANAGER_ID}),
            developer_telegram_ids=frozenset({DEVELOPER_ID}),
            settlement_timezone="Europe/Moscow",
            earnings_start_date=None,
        )
        self.storage = Storage(self.settings.database_path)
        self.langame = FakeLangame()
        self.bot = FakeBot()
        app = create_web_app(
            settings=self.settings, storage=self.storage, langame=self.langame, bot=self.bot
        )
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()
        self.storage.close()
        self.tmp.cleanup()

    async def call(self, method: str, path: str, user: int | None, body=None):
        headers = {}
        if user is not None:
            headers["Authorization"] = f"tma {make_init_data(user)}"
        response = await self.client.request(method, path, headers=headers, json=body)
        return response.status, await response.json()

    async def test_index_served(self):
        response = await self.client.get("/")
        self.assertEqual(response.status, 200)
        self.assertIn("telegram-web-app.js", await response.text())
        response = await self.client.get("/static/app.js")
        self.assertEqual(response.status, 200)

    async def test_requires_auth(self):
        status, data = await self.call("GET", "/api/me", None)
        self.assertEqual(status, 401)
        self.assertIn("error", data)

    async def test_stranger_has_no_access(self):
        status, data = await self.call("GET", "/api/me", STRANGER_ID)
        self.assertEqual(status, 200)
        self.assertFalse(data["access"])
        self.assertNotIn("<tg-emoji", data["message"])
        status, _ = await self.call("GET", "/api/shift/current", STRANGER_ID)
        self.assertEqual(status, 403)

    async def test_roles(self):
        _, dev = await self.call("GET", "/api/me", DEVELOPER_ID)
        self.assertTrue(dev["is_developer"] and dev["is_manager"])
        _, manager = await self.call("GET", "/api/me", MANAGER_ID)
        self.assertTrue(manager["is_manager"])
        self.assertFalse(manager["is_developer"])

        self.storage.register_admin(ADMIN_ID, "Иван")
        _, admin = await self.call("GET", "/api/me", ADMIN_ID)
        self.assertTrue(admin["is_admin"])
        self.assertTrue(admin["needs_link"])
        self.assertEqual(admin["balance"]["balance"], 0)

        status, _ = await self.call("GET", "/api/team", ADMIN_ID)
        self.assertEqual(status, 403)
        status, _ = await self.call("POST", "/api/managers", MANAGER_ID, {"name": "Петр", "telegram_id": "10"})
        self.assertEqual(status, 403)

    async def test_admin_lifecycle(self):
        status, data = await self.call("POST", "/api/admins", MANAGER_ID, {"name": "Иван", "telegram_id": str(ADMIN_ID)})
        self.assertEqual(status, 200, data)
        self.assertTrue(data["notified"])
        self.assertEqual(self.bot.messages[-1][0], ADMIN_ID)

        status, _ = await self.call("POST", "/api/admins", MANAGER_ID, {"name": "Иван", "telegram_id": str(ADMIN_ID)})
        self.assertEqual(status, 409)
        status, _ = await self.call("POST", "/api/admins", MANAGER_ID, {"name": "X", "telegram_id": "abc"})
        self.assertEqual(status, 400)

        status, linked = await self.call(
            "POST", "/api/admins", MANAGER_ID,
            {"name": "Ольга", "telegram_id": "41", "langame_id": "502"},
        )
        self.assertEqual(status, 200, linked)
        self.assertEqual(linked["langame_user_id"], 502)
        created = self.storage.get_link(41)
        self.assertEqual(created.user_id, 502)
        self.assertEqual(created.email, "other@club.ru")
        self.assertEqual(created.username, "Ольга")

        status, _ = await self.call(
            "POST", "/api/admins", MANAGER_ID,
            {"name": "Петр", "telegram_id": "42", "langame_id": "502"},
        )
        self.assertEqual(status, 409)
        status, _ = await self.call(
            "POST", "/api/admins", MANAGER_ID,
            {"name": "Петр", "telegram_id": "42", "langame_id": "999"},
        )
        self.assertEqual(status, 404)
        self.storage.remove_admin(41)

        status, team = await self.call("GET", "/api/team", MANAGER_ID)
        self.assertEqual([a["telegram_id"] for a in team["admins"]], [ADMIN_ID])

        status, data = await self.call("POST", "/api/link", ADMIN_ID, {"query": "admin@club.ru"})
        self.assertEqual(status, 200, data)
        self.assertFalse(data["me"]["needs_link"])
        self.assertEqual(data["synced"], 1)

        status, data = await self.call("POST", "/api/link", MANAGER_ID, {"query": "admin@club.ru"})
        self.assertEqual(status, 409)

        status, half = await self.call("GET", "/api/half-month", ADMIN_ID)
        self.assertEqual(status, 200, half)
        period = current_pay_period(today_in_timezone("Europe/Moscow"))
        in_period = self.langame.closed_shift.date_start.date() >= period.date_from
        self.assertEqual(half["summary"]["shifts"], 1 if in_period else 0)
        self.assertEqual(half["balance"]["shifts_count"], 1)
        self.assertAlmostEqual(half["balance"]["shift_earned"], 2500 + 100.0)

        _, me = await self.call("GET", "/api/me", ADMIN_ID)
        self.assertEqual(len(me["week"]["days"]), 7)
        self.assertIn(me["today"], me["week"]["days"])
        self.assertEqual(me["stats"]["period_shifts"], 1 if in_period else 0)
        self.assertGreaterEqual(me["period"]["days_to_payout"], 1)
        shift_day = self.langame.closed_shift.date_start.date().isoformat()
        if shift_day in me["week"]["days"]:
            self.assertIn(shift_day, me["week"]["shift_days"])
        _, manager_me = await self.call("GET", "/api/me", MANAGER_ID)
        self.assertEqual(manager_me["stats"]["admins"], 1)
        self.assertAlmostEqual(me["period_net"], half["summary"]["net"])
        self.assertAlmostEqual(manager_me["team_balance"], half["summary"]["net"])
        self.assertEqual(manager_me["week"]["shift_days"], me["week"]["shift_days"])

        status, current = await self.call("GET", "/api/shift/current", ADMIN_ID)
        self.assertEqual(current["mode"], "closed")
        self.assertEqual(current["earning"]["shift_id"], 7001)
        self.assertAlmostEqual(current["earning"]["bar_sales"], 500)

        self.langame.shifts.append(self.langame.open_shift)
        status, current = await self.call("GET", "/api/shift/current", ADMIN_ID)
        self.assertEqual(current["mode"], "open")
        self.assertAlmostEqual(current["shift"]["bar_total"], 200)
        self.assertIsNone(current["shift"]["total_revenue"])

        status, manager_view = await self.call("GET", "/api/shift/current", MANAGER_ID)
        self.assertEqual(manager_view["mode"], "manager")
        self.assertEqual(len(manager_view["shifts"]), 1)
        self.assertAlmostEqual(manager_view["shifts"][0]["shift"]["total_revenue"], 4000)
        self.assertAlmostEqual(manager_view["shifts"][0]["shift"]["bar_share_percent"], 5)

        status, card = await self.call("GET", f"/api/admins/{ADMIN_ID}", MANAGER_ID)
        self.assertEqual(status, 200, card)
        self.assertEqual(card["last_earning"]["shift_id"], 7001)

        status, report = await self.call("GET", "/api/shifts/7001/report", MANAGER_ID)
        self.assertEqual(status, 200, report)
        self.assertFalse(report["open"])
        status, report = await self.call("GET", "/api/shifts/7002/report", MANAGER_ID)
        self.assertTrue(report["open"])
        status, _ = await self.call("GET", "/api/shifts/1/report", MANAGER_ID)
        self.assertEqual(status, 404)

        status, payroll = await self.call("GET", "/api/payroll", MANAGER_ID)
        self.assertEqual(status, 200, payroll)
        self.assertEqual(len(payroll["rows"]), 1)

        status, data = await self.call("POST", "/api/payroll/export", MANAGER_ID)
        self.assertEqual(status, 200, data)
        self.assertEqual(self.bot.documents[-1][0], MANAGER_ID)
        self.assertTrue(self.bot.documents[-1][1].endswith(".csv"))

        status, board = await self.call("GET", "/api/leaderboard", MANAGER_ID)
        self.assertEqual(status, 200)
        self.assertEqual(len(board["rows"]), 1 if in_period else 0)

        status, data = await self.call("DELETE", f"/api/admins/{ADMIN_ID}", MANAGER_ID)
        self.assertEqual(status, 200, data)
        _, me = await self.call("GET", "/api/me", ADMIN_ID)
        self.assertFalse(me["access"])

    async def test_fines(self):
        self.storage.register_admin(ADMIN_ID, "Иван")
        status, data = await self.call(
            "POST", "/api/fines", MANAGER_ID,
            {"telegram_id": ADMIN_ID, "amount": "300,5", "reason": "Опоздание", "shift_id": ""},
        )
        self.assertEqual(status, 200, data)
        fine_id = data["fine"]["id"]
        self.assertEqual(self.bot.messages[-1][0], ADMIN_ID)

        status, mine = await self.call("GET", "/api/my/fines", ADMIN_ID)
        self.assertEqual([f["id"] for f in mine["fines"]], [fine_id])
        self.assertAlmostEqual(mine["fines"][0]["amount"], 300.5)

        status, _ = await self.call("POST", "/api/fines", MANAGER_ID, {"telegram_id": ADMIN_ID, "amount": "x", "reason": "r"})
        self.assertEqual(status, 400)
        status, _ = await self.call("POST", "/api/fines", ADMIN_ID, {"telegram_id": ADMIN_ID, "amount": "1", "reason": "r"})
        self.assertEqual(status, 403)

        status, filtered = await self.call("GET", f"/api/fines?telegram_id={ADMIN_ID}", MANAGER_ID)
        self.assertEqual(len(filtered["fines"]), 1)

        status, _ = await self.call("DELETE", f"/api/fines/{fine_id}", MANAGER_ID)
        self.assertEqual(status, 200)
        status, _ = await self.call("DELETE", f"/api/fines/{fine_id}", MANAGER_ID)
        self.assertEqual(status, 409)
        status, mine = await self.call("GET", "/api/my/fines", ADMIN_ID)
        self.assertEqual(mine["fines"], [])

    async def test_settings_and_broadcast(self):
        status, data = await self.call("PUT", "/api/settings/bar-percent", MANAGER_ID, {"value": "15"})
        self.assertEqual(status, 200, data)
        _, data = await self.call("GET", "/api/settings/bar-percent", MANAGER_ID)
        self.assertEqual(data["value"], 15)
        status, _ = await self.call("PUT", "/api/settings/bar-percent", MANAGER_ID, {"value": "150"})
        self.assertEqual(status, 400)

        status, _ = await self.call("POST", "/api/broadcast", MANAGER_ID, {"text": "Привет"})
        self.assertEqual(status, 404)
        self.storage.register_admin(ADMIN_ID, "Иван")
        status, data = await self.call("POST", "/api/broadcast", MANAGER_ID, {"text": "Привет"})
        self.assertEqual(status, 200)
        self.assertEqual(data["sent"], 1)
        self.assertIn("Привет", self.bot.messages[-1][1])

    async def test_developer_manages_managers(self):
        status, data = await self.call("POST", "/api/managers", DEVELOPER_ID, {"name": "Петр", "telegram_id": "10"})
        self.assertEqual(status, 200, data)
        _, me = await self.call("GET", "/api/me", 10)
        self.assertTrue(me["is_manager"])
        _, team = await self.call("GET", "/api/team", DEVELOPER_ID)
        removable = {m["telegram_id"]: m["removable"] for m in team["managers"]}
        self.assertEqual(removable, {MANAGER_ID: False, 10: True})
        status, _ = await self.call("DELETE", f"/api/managers/{MANAGER_ID}", DEVELOPER_ID)
        self.assertEqual(status, 409)
        status, _ = await self.call("DELETE", "/api/managers/10", DEVELOPER_ID)
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
