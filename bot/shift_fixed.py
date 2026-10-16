from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bot.config import Settings
from bot.langame_api import WorkingShift

# Shifts starting before this hour (local) belong to previous club day.
CLUB_DAY_ROLLOVER_HOUR = 10
# Paid window is 15:00–03:00, and 15:00–08:00 on Friday and Saturday.
# Opening earlier does not earn the time before 15:00.
PAY_START_HOUR = 15
WEEKDAY_CUTOFF_HOUR = 3
WEEKEND_CUTOFF_HOUR = 8
WEEKEND_CLUB_DAYS = (4, 5)  # Friday, Saturday


@dataclass(frozen=True)
class FixedShare:
    shift_id: int
    worked_hours: float
    fixed_work: float
    fixed_cleaning: float

    @property
    def fixed_total(self) -> float:
        return self.fixed_work + self.fixed_cleaning


def round_hours_to_quarter(hours: float) -> float:
    if hours <= 0:
        return 0.0
    quarters = round(hours * 4)
    return quarters / 4


def _as_club_time(value: datetime, tz: ZoneInfo) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)


def local_shift_start(shift: WorkingShift, settings: Settings) -> datetime | None:
    if shift.date_start is None:
        return None
    return _as_club_time(shift.date_start, ZoneInfo(settings.settlement_timezone))


def club_day_date(shift: WorkingShift, settings: Settings):
    local_start = local_shift_start(shift, settings)
    if local_start is None:
        return None
    day = local_start.date()
    if local_start.hour < CLUB_DAY_ROLLOVER_HOUR:
        day -= timedelta(days=1)
    return day


def is_weekend_club_day(day) -> bool:
    return day.weekday() in WEEKEND_CLUB_DAYS


def shift_pay_start(day, tz: ZoneInfo) -> datetime:
    return datetime(day.year, day.month, day.day, PAY_START_HOUR, 0, tzinfo=tz)


def shift_pay_cutoff(day, tz: ZoneInfo) -> datetime:
    hour = WEEKEND_CUTOFF_HOUR if is_weekend_club_day(day) else WEEKDAY_CUTOFF_HOUR
    morning = day + timedelta(days=1)
    return datetime(morning.year, morning.month, morning.day, hour, 0, tzinfo=tz)


def club_day_hour_cap(day, settings: Settings) -> float:
    extra = WEEKEND_CUTOFF_HOUR - WEEKDAY_CUTOFF_HOUR if is_weekend_club_day(day) else 0
    return settings.shift_standard_hours + extra


def billable_shift_hours(
    shift: WorkingShift,
    settings: Settings,
    *,
    until: datetime | None = None,
) -> float:
    """Hours inside 15:00–03:00, or 15:00–08:00 on Friday and Saturday."""
    if shift.date_start is None:
        return 0.0
    day = club_day_date(shift, settings)
    if day is None:
        return 0.0
    tz = ZoneInfo(settings.settlement_timezone)
    start = _as_club_time(shift.date_start, tz)
    if until is None:
        if shift.date_stop is None:
            return 0.0
        until = _as_club_time(shift.date_stop, tz)
    else:
        until = _as_club_time(until, tz)
    paid_from = max(start, shift_pay_start(day, tz))
    paid_until = min(until, shift_pay_cutoff(day, tz))
    if paid_until <= paid_from:
        return 0.0
    return round_hours_to_quarter((paid_until - paid_from).total_seconds() / 3600)


def shift_worked_hours(shift: WorkingShift, settings: Settings | None = None) -> float:
    if settings is not None:
        return billable_shift_hours(shift, settings)
    if shift.date_start is None or shift.date_stop is None:
        return 0.0
    delta = shift.date_stop - shift.date_start
    return round_hours_to_quarter(delta.total_seconds() / 3600)


def club_shift_key(shift: WorkingShift, settings: Settings) -> str | None:
    day = club_day_date(shift, settings)
    if day is None:
        return None
    return f"{shift.club_id}:{day.isoformat()}"


def estimate_open_shift_fixed(
    shift: WorkingShift,
    *,
    settings: Settings,
    is_first_opener: bool,
) -> FixedShare:
    if shift.date_start is None:
        return FixedShare(shift.id, 0.0, 0.0, 0.0)
    tz = ZoneInfo(settings.settlement_timezone)
    now = datetime.now(tz)
    day = club_day_date(shift, settings)
    hours = billable_shift_hours(shift, settings, until=now)
    if day is not None:
        hours = min(hours, club_day_hour_cap(day, settings))
    hourly = settings.fixed_shift_work / settings.shift_standard_hours
    fixed_work = round(hours * hourly, 2)
    cleaning = settings.fixed_cleaning if is_first_opener else 0.0
    return FixedShare(shift.id, hours, fixed_work, cleaning)


def first_opener_id(
    shifts: list[WorkingShift],
    settings: Settings,
    club_key: str | None,
) -> int | None:
    """Earliest shift of the club day, linked or not, open or closed.

    Cleaning belongs to whoever opened the club day first. A shift that the bot
    does not pay still counts: the later paid admin is not the opener.
    """
    if not club_key:
        return None
    candidates = [
        shift
        for shift in shifts
        if shift.date_start is not None and club_shift_key(shift, settings) == club_key
    ]
    if not candidates:
        return None
    opener = min(candidates, key=lambda shift: (shift.date_start, shift.id))
    return opener.id


def distribute_club_shift_fixed(
    shifts: list[WorkingShift],
    settings: Settings,
    *,
    first_opener_id: int | None = None,
) -> dict[int, FixedShare]:
    if not shifts:
        return {}

    ordered = sorted(shifts, key=lambda item: (item.date_start or datetime.min, item.id))
    hours_by_shift = {shift.id: billable_shift_hours(shift, settings) for shift in ordered}
    total_hours = sum(hours_by_shift.values())
    if total_hours <= 0:
        return {
            shift.id: FixedShare(shift.id, 0.0, 0.0, 0.0)
            for shift in ordered
        }

    club_day = club_day_date(ordered[0], settings)
    hour_cap = club_day_hour_cap(club_day, settings) if club_day is not None else settings.shift_standard_hours
    billable_hours = min(total_hours, hour_cap)
    work_pool = settings.fixed_shift_work * billable_hours / settings.shift_standard_hours
    work_parts = _split_pool(work_pool, [hours_by_shift[shift.id] for shift in ordered])

    # None means "first of this paid list" (callers that already filtered).
    # An explicit id that is not in the list awards cleaning to nobody here.
    if first_opener_id is None:
        first_opener_id = ordered[0].id
    result: dict[int, FixedShare] = {}
    for shift, fixed_work in zip(ordered, work_parts, strict=True):
        cleaning = settings.fixed_cleaning if shift.id == first_opener_id else 0.0
        result[shift.id] = FixedShare(
            shift_id=shift.id,
            worked_hours=hours_by_shift[shift.id],
            fixed_work=fixed_work,
            fixed_cleaning=cleaning,
        )
    return result


def group_shifts_by_club_day(
    shifts: list[WorkingShift],
    settings: Settings,
) -> dict[str, list[WorkingShift]]:
    groups: dict[str, list[WorkingShift]] = {}
    for shift in shifts:
        key = club_shift_key(shift, settings)
        if key is None:
            continue
        groups.setdefault(key, []).append(shift)
    for key in groups:
        groups[key].sort(key=lambda item: item.date_start or datetime.min)
    return groups


def _split_pool(total: float, weights: list[float]) -> list[float]:
    if not weights:
        return []
    weight_sum = sum(weights)
    if weight_sum <= 0:
        return [0.0] * len(weights)

    total_kopecks = round(total * 100)
    allocated = 0
    parts: list[float] = []
    for index, weight in enumerate(weights):
        if index == len(weights) - 1:
            share_kopecks = total_kopecks - allocated
        else:
            share_kopecks = round(total_kopecks * weight / weight_sum)
            allocated += share_kopecks
        parts.append(share_kopecks / 100)
    return parts
