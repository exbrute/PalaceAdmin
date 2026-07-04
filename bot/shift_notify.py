from __future__ import annotations

import logging
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot.messaging import send as send_message

from bot.config import Settings
from bot.half_month_report import prepare_half_month_report
from bot.langame_api import LangameApiError, LangameClient
from bot.pay_period import completed_pay_period, is_half_month_closing_day
from bot.roles import list_manager_telegram_ids
from bot.services import get_bar_bonus_percent
from bot.shift_close_export import (
    build_shift_bar_breakdown_csv,
    load_shift_bar_rows,
    shift_bar_csv_filename,
)
from bot.shift_stats import build_shift_close_report
from bot.storage import Storage
from bot.texts import manager_shift_closed, manager_shift_opened

logger = logging.getLogger(__name__)

EVENT_SHIFT_OPENED = "opened"
EVENT_SHIFT_CLOSED = "closed"
NOTIFICATION_MAX_AGE_HOURS = 4


def _shift_event_datetime(
    shift,
    event_type: str,
    tz: ZoneInfo,
) -> datetime | None:
    raw = shift.date_start if event_type == EVENT_SHIFT_OPENED else shift.date_stop
    if raw is None:
        return None
    if raw.tzinfo is None:
        return raw.replace(tzinfo=tz)
    return raw.astimezone(tz)


def _shift_is_eligible_for_notification(
    shift,
    event_type: str,
    *,
    settings: Settings,
    now: datetime,
) -> bool:
    tz = ZoneInfo(settings.settlement_timezone)
    event_at = _shift_event_datetime(shift, event_type, tz)
    if event_at is None:
        return False

    if settings.earnings_start_date is not None:
        if event_at.date() < settings.earnings_start_date:
            return False

    age_hours = (now - event_at).total_seconds() / 3600
    return 0 <= age_hours <= NOTIFICATION_MAX_AGE_HOURS


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


async def notify_managers_document(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    filename: str,
    content: str,
    caption: str,
) -> None:
    settings: Settings = context.application.bot_data["settings"]
    storage: Storage = context.application.bot_data["storage"]
    buffer = BytesIO(content.encode("utf-8-sig"))
    buffer.name = filename
    for telegram_id in list_manager_telegram_ids(settings, storage):
        try:
            await context.bot.send_document(
                chat_id=telegram_id,
                document=buffer,
                filename=filename,
                caption=caption,
                parse_mode=ParseMode.HTML if "<tg-emoji" in caption else None,
            )
            buffer.seek(0)
        except Exception as exc:
            logger.warning("Failed to send document to manager %s: %s", telegram_id, exc)
            buffer.seek(0)


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

    try:
        shifts = api.get_working_shifts()
    except LangameApiError as exc:
        logger.warning("Shift notification poll failed: %s", exc)
        return

    for shift in shifts:
        if shift.date_start is None or shift.date_stop is not None:
            continue
        if storage.has_shift_notification(shift.id, EVENT_SHIFT_OPENED):
            continue
        link = storage.get_link_by_user_id(shift.user_id)
        if link is None:
            continue
        if not _shift_is_eligible_for_notification(
            shift, EVENT_SHIFT_OPENED, settings=settings, now=now
        ):
            storage.mark_shift_notification(shift.id, EVENT_SHIFT_OPENED)
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

    bar_percent = get_bar_bonus_percent(storage, settings)
    for shift in shifts:
        if shift.date_stop is None:
            continue
        if storage.has_shift_notification(shift.id, EVENT_SHIFT_CLOSED):
            continue
        link = storage.get_link_by_user_id(shift.user_id)
        if link is None:
            continue
        if not _shift_is_eligible_for_notification(
            shift, EVENT_SHIFT_CLOSED, settings=settings, now=now
        ):
            storage.mark_shift_notification(shift.id, EVENT_SHIFT_CLOSED)
            continue
        name = Storage.admin_name(link)
        report = build_shift_close_report(api, storage, settings, link, shift)
        started_at = _format_shift_time(shift.date_start)
        stopped_at = _format_shift_time(shift.date_stop)
        text = manager_shift_closed(
            name=name,
            shift_id=shift.id,
            stopped_at=stopped_at,
            cash_in_register=report.cash_in_register,
            total_revenue=report.total_revenue,
            nal_revenue=report.nal_revenue,
            beznal_revenue=report.beznal_revenue,
            club_revenue=report.club_revenue,
            bar_revenue=report.bar_revenue,
            bar_share_percent=report.bar_share_percent,
            net_salary=report.net_salary,
            fixed=report.fixed,
            bar_bonus=report.bar_bonus,
            fines=report.fines,
            bar_bonus_percent=bar_percent,
        )
        await notify_managers(context, text)

        bar_rows = load_shift_bar_rows(api, shift, bar_percent)
        csv_content = build_shift_bar_breakdown_csv(
            admin_name=name,
            shift_id=shift.id,
            shift_started=started_at,
            shift_stopped=stopped_at,
            rows=bar_rows,
            bar_bonus_percent=bar_percent,
            bar_total=report.bar_revenue,
            bar_bonus_total=report.bar_bonus,
        )
        filename = shift_bar_csv_filename(admin_name=name, shift_id=shift.id)
        await notify_managers_document(
            context,
            filename=filename,
            content=csv_content,
            caption=f"Смена #{shift.id} · {name} · бар",
        )

        storage.mark_shift_notification(shift.id, EVENT_SHIFT_CLOSED)
        logger.info("Notified managers: shift #%s closed (%s)", shift.id, name)
        if shift.date_stop is not None:
            await maybe_notify_half_month_close(context, shift_stop=shift.date_stop)
