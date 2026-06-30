from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram.ext import ContextTypes

from bot.messaging import send as send_message

from bot.config import Settings
from bot.half_month_report import prepare_half_month_report
from bot.langame_api import LangameApiError, LangameClient
from bot.pay_period import completed_pay_period, is_half_month_closing_day
from bot.roles import list_manager_telegram_ids
from bot.services import get_bar_bonus_percent
from bot.shift_stats import build_shift_close_report
from bot.storage import Storage
from bot.texts import manager_shift_closed, manager_shift_opened

logger = logging.getLogger(__name__)

SHIFT_OPEN_FROM = (13, 58)
SHIFT_OPEN_TO = (16, 0)
SHIFT_CLOSE_FROM = (3, 0)
SHIFT_CLOSE_TO = (9, 0)

EVENT_SHIFT_OPENED = "opened"
EVENT_SHIFT_CLOSED = "closed"


def _minutes(hour: int, minute: int) -> int:
    return hour * 60 + minute


def _in_time_window(now: datetime, start: tuple[int, int], end: tuple[int, int]) -> bool:
    current = _minutes(now.hour, now.minute)
    return _minutes(start[0], start[1]) <= current <= _minutes(end[0], end[1])


def _format_shift_time(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.strftime("%d.%m.%Y %H:%M")


async def notify_managers(context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    settings: Settings = context.application.bot_data["settings"]
    storage: Storage = context.application.bot_data["storage"]
    for telegram_id in list_manager_telegram_ids(settings, storage):
        try:
            await send_message(context, telegram_id, text)
        except Exception as exc:
            logger.warning("Failed to notify manager %s: %s", telegram_id, exc)


def _has_open_admin_shifts(api: LangameClient, storage: Storage) -> bool:
    try:
        shifts = api.get_working_shifts()
    except LangameApiError:
        return True
    for shift in shifts:
        if shift.date_stop is not None:
            continue
        if storage.get_link_by_user_id(shift.user_id) is not None:
            return True
    return False


async def maybe_notify_half_month_close(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    shift_stop: datetime,
) -> None:
    settings: Settings = context.application.bot_data["settings"]
    api: LangameClient = context.application.bot_data["api"]
    storage: Storage = context.application.bot_data["storage"]
    tz = ZoneInfo(settings.settlement_timezone)
    close_day = shift_stop.astimezone(tz).date()

    if not is_half_month_closing_day(close_day):
        return
    if _has_open_admin_shifts(api, storage):
        return

    period = completed_pay_period(close_day)
    if period is None:
        return
    if storage.has_half_month_notification(period.cycle_key):
        return

    report, error = prepare_half_month_report(api, storage, settings, period)
    if error or report is None:
        logger.warning("Half-month report failed: %s", error)
        return

    await notify_managers(context, report)
    storage.mark_half_month_notification(period.cycle_key)
    logger.info("Half-month report sent for %s", period.cycle_key)


async def poll_shift_notifications(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    api: LangameClient = context.application.bot_data["api"]
    storage: Storage = context.application.bot_data["storage"]

    tz = ZoneInfo(settings.settlement_timezone)
    now = datetime.now(tz)
    in_open = _in_time_window(now, SHIFT_OPEN_FROM, SHIFT_OPEN_TO)
    in_close = _in_time_window(now, SHIFT_CLOSE_FROM, SHIFT_CLOSE_TO)
    if not in_open and not in_close:
        return

    try:
        shifts = api.get_working_shifts()
    except LangameApiError as exc:
        logger.warning("Shift notification poll failed: %s", exc)
        return

    if in_open:
        for shift in shifts:
            if shift.date_start is None or shift.date_stop is not None:
                continue
            if storage.has_shift_notification(shift.id, EVENT_SHIFT_OPENED):
                continue
            link = storage.get_link_by_user_id(shift.user_id)
            if link is None:
                continue
            name = Storage.admin_name(link)
            text = manager_shift_opened(
                name=name,
                shift_id=shift.id,
                started_at=_format_shift_time(shift.date_start),
                cash_start=shift.cash_start,
            )
            await notify_managers(context, text)
            storage.mark_shift_notification(shift.id, EVENT_SHIFT_OPENED)
            logger.info("Notified managers: shift #%s opened (%s)", shift.id, name)

    if in_close:
        for shift in shifts:
            if shift.date_stop is None:
                continue
            if storage.has_shift_notification(shift.id, EVENT_SHIFT_CLOSED):
                continue
            link = storage.get_link_by_user_id(shift.user_id)
            if link is None:
                continue
            name = Storage.admin_name(link)
            report = build_shift_close_report(api, storage, settings, link, shift)
            bar_percent = get_bar_bonus_percent(storage, settings)
            text = manager_shift_closed(
                name=name,
                shift_id=shift.id,
                stopped_at=_format_shift_time(shift.date_stop),
                cash_in_register=report.cash_in_register,
                total_revenue=report.total_revenue,
                club_revenue=report.club_revenue,
                bar_revenue=report.bar_revenue,
                net_salary=report.net_salary,
                fixed=report.fixed,
                bar_bonus=report.bar_bonus,
                fines=report.fines,
                bar_bonus_percent=bar_percent,
            )
            await notify_managers(context, text)
            storage.mark_shift_notification(shift.id, EVENT_SHIFT_CLOSED)
            logger.info("Notified managers: shift #%s closed (%s)", shift.id, name)
            if shift.date_stop is not None:
                await maybe_notify_half_month_close(context, shift_stop=shift.date_stop)
