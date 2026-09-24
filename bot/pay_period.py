from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from bot.emojis import e

FIRST_HALF_LAST_DAY = 15
SECOND_HALF_FIRST_DAY = 16


@dataclass(frozen=True)
class PayPeriod:
    date_from: date
    date_to: date
    title: str
    next_payout: date
    half_label: str
    cycle_key: str


def today_in_timezone(tz_name: str) -> date:
    return datetime.now(ZoneInfo(tz_name)).date()


def last_day_of_month(day: date) -> int:
    return calendar.monthrange(day.year, day.month)[1]


def is_first_half_day(day: date) -> bool:
    return day.day < SECOND_HALF_FIRST_DAY


def is_settlement_day(day: date) -> bool:
    return day.day == 1 or day.day == SECOND_HALF_FIRST_DAY


def is_half_month_closing_day(day: date) -> bool:
    return day.day == FIRST_HALF_LAST_DAY or day.day == last_day_of_month(day)


def _next_month_first(day: date) -> date:
    if day.month == 12:
        return date(day.year + 1, 1, 1)
    return date(day.year, day.month + 1, 1)


def _period_for_first_half(year: int, month: int, *, date_to: int | None = None) -> PayPeriod:
    last_to = date_to if date_to is not None else FIRST_HALF_LAST_DAY
    day = date(year, month, 1)
    date_from = day.replace(day=1)
    date_end = day.replace(day=last_to)
    half_label = f"1–15.{day.strftime('%m.%Y')}"
    return PayPeriod(
        date_from=date_from,
        date_to=date_end,
        title=f"{e('money_bag')} Зарплата за {half_label}",
        next_payout=day.replace(day=SECOND_HALF_FIRST_DAY),
        half_label=half_label,
        cycle_key=f"{year}-{month:02d}-h1",
    )


def _period_for_second_half(year: int, month: int, *, date_to: int | None = None) -> PayPeriod:
    last = last_day_of_month(date(year, month, 1))
    last_to = date_to if date_to is not None else last
    day = date(year, month, 1)
    date_from = day.replace(day=SECOND_HALF_FIRST_DAY)
    date_end = day.replace(day=last_to)
    half_label = f"16–{last}.{day.strftime('%m.%Y')}"
    return PayPeriod(
        date_from=date_from,
        date_to=date_end,
        title=f"{e('money_bag')} Зарплата за {half_label}",
        next_payout=_next_month_first(day),
        half_label=half_label,
        cycle_key=f"{year}-{month:02d}-h2",
    )


def unpaid_pay_period(today: date, *, settled: bool = False) -> PayPeriod:
    """Period that still counts toward the live balance.

    On the 1st/16th, keep the just-finished half-month until settlement runs.
    After that (or on other days) use the current half-month.
    """
    if is_settlement_day(today) and not settled:
        if today.day == 1:
            previous = today - timedelta(days=1)
            return _period_for_second_half(previous.year, previous.month)
        return _period_for_first_half(today.year, today.month)
    return current_pay_period(today)


def current_pay_period(today: date) -> PayPeriod:
    if is_first_half_day(today):
        period = _period_for_first_half(today.year, today.month)
        return PayPeriod(
            date_from=period.date_from,
            date_to=today,
            title=period.title,
            next_payout=period.next_payout,
            half_label=period.half_label,
            cycle_key=period.cycle_key,
        )
    period = _period_for_second_half(today.year, today.month)
    return PayPeriod(
        date_from=period.date_from,
        date_to=today,
        title=period.title,
        next_payout=period.next_payout,
        half_label=period.half_label,
        cycle_key=period.cycle_key,
    )


def completed_pay_period(closing_day: date) -> PayPeriod | None:
    if closing_day.day == FIRST_HALF_LAST_DAY:
        return _period_for_first_half(closing_day.year, closing_day.month)
    if closing_day.day == last_day_of_month(closing_day):
        return _period_for_second_half(closing_day.year, closing_day.month)
    return None


def format_pay_period_header(period: PayPeriod) -> str:
    return (
        f"{period.title}\n"
        f"{e('date')} Период: {period.date_from.strftime('%d.%m.%Y')} — "
        f"{period.date_to.strftime('%d.%m.%Y')}\n"
        f"{e('money')} Выплата: {period.next_payout.strftime('%d.%m.%Y')}"
    )
