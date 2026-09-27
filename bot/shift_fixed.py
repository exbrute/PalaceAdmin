from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bot.config import Settings
from bot.langame_api import WorkingShift

# Shifts starting before this hour (local) belong to previous club day.
CLUB_DAY_ROLLOVER_HOUR = 10


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


def shift_worked_hours(shift: WorkingShift) -> float:
    if shift.date_start is None or shift.date_stop is None:
        return 0.0
    delta = shift.date_stop - shift.date_start
    return round_hours_to_quarter(delta.total_seconds() / 3600)


def club_shift_key(shift: WorkingShift, settings: Settings) -> str | None:
    if shift.date_start is None:
        return None
    tz = ZoneInfo(settings.settlement_timezone)
    local_start = shift.date_start.astimezone(tz)
    day = local_start.date()
    if local_start.hour < CLUB_DAY_ROLLOVER_HOUR:
        day -= timedelta(days=1)
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
    start = shift.date_start.astimezone(tz)
    hours = round_hours_to_quarter(max(0.0, (now - start).total_seconds() / 3600))
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
    hours_by_shift = {shift.id: shift_worked_hours(shift) for shift in ordered}
    total_hours = sum(hours_by_shift.values())
    if total_hours <= 0:
        return {
            shift.id: FixedShare(shift.id, 0.0, 0.0, 0.0)
            for shift in ordered
        }

    billable_hours = min(total_hours, settings.shift_standard_hours)
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
