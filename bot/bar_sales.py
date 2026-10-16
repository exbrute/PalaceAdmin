from __future__ import annotations

import logging
from datetime import date, timedelta

from telegram import Bot
from telegram.ext import ContextTypes

from bot.config import Settings
from bot.langame_api import LangameApiError, LangameClient, WorkingShift, sale_counts_as_bar
from bot.messaging import send as send_message, send_via_bot
from bot.ledger import find_open_shift, shift_eligible_for_earnings, sync_admin_shifts
from bot.services import get_bar_bonus_percent
from bot.storage import ROLE_ADMIN, Storage
from bot.shift_notify import poll_shift_notifications
from bot.salary import shift_date_range
from bot.texts import admin_shift_closed, bar_bonus_added

logger = logging.getLogger(__name__)


def _user_to_telegram(storage: Storage) -> dict[int, int]:
    mapping: dict[int, int] = {}
    for link in storage.list_links(ROLE_ADMIN):
        if link.user_id:
            mapping[link.user_id] = link.telegram_id
    return mapping


def _shift_bar_bonus(storage: Storage, telegram_id: int, shift_id: int, fallback: float) -> float:
    return fallback


def backfill_shift_bar_credits(
    api: LangameClient,
    storage: Storage,
    settings: Settings,
    telegram_id: int,
    shift: WorkingShift,
) -> list[tuple[int, float, float, str, int]]:
    """Credit bar bonus for shift sales that were not credited yet."""
    if not shift_eligible_for_earnings(shift, settings):
        return []

    date_from, date_to = shift_date_range(shift)
    if date_from is None or date_to is None:
        return []

    try:
        sales = api.get_product_sales(date_from=date_from, date_to=date_to)
    except LangameApiError as exc:
        logger.warning("Bar sales backfill failed for shift #%s: %s", shift.id, exc)
        return []

    percent = get_bar_bonus_percent(storage, settings)
    credited: list[tuple[int, float, float, str, int]] = []
    for sale in sales:
        if sale.working_shift_id != shift.id or not sale_counts_as_bar(sale):
            continue
        if storage.has_bar_sale_credit(sale.id):
            continue

        sale_amount = sale.price_sale * sale.count
        bonus = sale_amount * percent / 100
        if bonus <= 0:
            continue

        if storage.add_bar_sale_credit(
            sale_id=sale.id,
            telegram_id=telegram_id,
            shift_id=shift.id,
            sale_amount=sale_amount,
            bonus_amount=bonus,
        ):
            credited.append((telegram_id, bonus, sale_amount, sale.product_name, sale.count))

    return credited


def sync_new_bar_sales(
    api: LangameClient,
    storage: Storage,
    settings: Settings,
) -> list[tuple[int, float, float, str, int]]:
    """Credit bar bonus for each new bar sale."""
    today = date.today()
    start = settings.earnings_start_date
    date_from = today - timedelta(days=1)
    if start is not None and start > date_from:
        date_from = start

    try:
        sales = api.get_product_sales(date_from=date_from, date_to=today)
        shifts = api.get_working_shifts()
    except LangameApiError as exc:
        logger.warning("Bar sales poll failed: %s", exc)
        return []

    shift_by_id = {shift.id: shift for shift in shifts}
    shift_users = {shift.id: shift.user_id for shift in shifts}
    user_to_tg = _user_to_telegram(storage)
    credited: list[tuple[int, float, float, str, int]] = []

    for sale in sales:
        if not sale_counts_as_bar(sale):
            continue
        if storage.has_bar_sale_credit(sale.id):
            continue

        user_id = shift_users.get(sale.working_shift_id)
        if not user_id:
            continue

        shift = shift_by_id.get(sale.working_shift_id)
        if shift is not None and not shift_eligible_for_earnings(shift, settings):
            continue

        telegram_id = user_to_tg.get(user_id)
        if not telegram_id:
            continue

        existing_earning = storage.get_shift_earning(sale.working_shift_id)
        if existing_earning is not None:
            continue

        sale_amount = sale.price_sale * sale.count
        bonus = sale_amount * get_bar_bonus_percent(storage, settings) / 100
        if bonus <= 0:
            continue

        if storage.add_bar_sale_credit(
            sale_id=sale.id,
            telegram_id=telegram_id,
            shift_id=sale.working_shift_id,
            sale_amount=sale_amount,
            bonus_amount=bonus,
        ):
            credited.append((telegram_id, bonus, sale_amount, sale.product_name, sale.count))

    return credited


async def notify_admin_shift_closed(
    bot: Bot,
    storage: Storage,
    telegram_id: int,
    shift_id: int,
) -> None:
    earning = storage.get_shift_earning(shift_id)
    if earning is None:
        return
    bar_bonus = _shift_bar_bonus(storage, telegram_id, shift_id, earning.bar_bonus)
    fines = storage.sum_fines(telegram_id, shift_id)
    text = admin_shift_closed(
        shift_id=shift_id,
        fixed=earning.fixed_salary,
        bar_bonus=bar_bonus,
        fines=fines,
    )
    try:
        await send_via_bot(bot, telegram_id, text)
    except Exception as exc:
        logger.warning("Failed to notify admin %s about shift #%s: %s", telegram_id, shift_id, exc)


async def poll_bar_sales(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    api: LangameClient = context.application.bot_data["api"]
    storage: Storage = context.application.bot_data["storage"]

    credited = sync_new_bar_sales(api, storage, settings)
    for link in storage.list_links(ROLE_ADMIN):
        if link.user_id == 0:
            continue
        open_shift = find_open_shift(api, link.user_id)
        if open_shift is not None:
            credited.extend(
                backfill_shift_bar_credits(
                    api, storage, settings, link.telegram_id, open_shift
                )
            )
    bar_percent = get_bar_bonus_percent(storage, settings)
    if credited:
        logger.info("Credited %d bar sale(s)", len(credited))
        for telegram_id, bonus, sale_amount, product_name, product_count in credited:
            try:
                await send_message(
                    context,
                    telegram_id,
                    bar_bonus_added(bonus, bar_percent, sale_amount, product_name, product_count),
                )
            except Exception as exc:
                logger.warning("Failed to notify admin %s about bar sale: %s", telegram_id, exc)

    for link in storage.list_links(ROLE_ADMIN):
        if link.user_id == 0:
            continue
        _, error, synced_shift_ids = sync_admin_shifts(api, storage, settings, link)
        if error:
            logger.warning("Shift sync failed for %s: %s", link.telegram_id, error)
            continue
        for shift_id in synced_shift_ids:
            await notify_admin_shift_closed(context.bot, storage, link.telegram_id, shift_id)

    await poll_shift_notifications(context)
