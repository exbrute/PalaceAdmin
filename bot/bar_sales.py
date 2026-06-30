from __future__ import annotations

import logging
from datetime import date, timedelta

from telegram.ext import ContextTypes

from bot.config import Settings
from bot.langame_api import LangameApiError, LangameClient
from bot.messaging import send as send_message
from bot.ledger import sync_admin_shifts
from bot.salary import format_money
from bot.services import get_bar_bonus_percent
from bot.storage import ROLE_ADMIN, Storage
from bot.shift_notify import poll_shift_notifications
from bot.texts import bar_bonus_added, shift_fixed_added

logger = logging.getLogger(__name__)


def _user_to_telegram(storage: Storage) -> dict[int, int]:
    mapping: dict[int, int] = {}
    for link in storage.list_links(ROLE_ADMIN):
        if link.user_id:
            mapping[link.user_id] = link.telegram_id
    return mapping


def sync_new_bar_sales(
    api: LangameClient,
    storage: Storage,
    settings: Settings,
) -> list[tuple[int, float, float]]:
    """Credit bar bonus for each new bar sale. Returns (telegram_id, bonus, sale_amount)."""
    today = date.today()
    date_from = today - timedelta(days=1)

    try:
        sales = api.get_product_sales(date_from=date_from, date_to=today)
        shifts = api.get_working_shifts()
    except LangameApiError as exc:
        logger.warning("Bar sales poll failed: %s", exc)
        return []

    shift_users = {shift.id: shift.user_id for shift in shifts}
    user_to_tg = _user_to_telegram(storage)
    credited: list[tuple[int, float, float]] = []

    for sale in sales:
        if sale.cancel != 0:
            continue
        if storage.has_bar_sale_credit(sale.id):
            continue

        user_id = shift_users.get(sale.working_shift_id)
        if not user_id:
            continue

        telegram_id = user_to_tg.get(user_id)
        if not telegram_id:
            continue

        existing_earning = storage.get_shift_earning(sale.working_shift_id)
        if existing_earning is not None and (
            existing_earning.gross_amount > existing_earning.fixed_salary + 0.01
        ):
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
            credited.append((telegram_id, bonus, sale_amount))

    return credited


async def poll_bar_sales(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    api: LangameClient = context.application.bot_data["api"]
    storage: Storage = context.application.bot_data["storage"]

    credited = sync_new_bar_sales(api, storage, settings)
    bar_percent = get_bar_bonus_percent(storage, settings)
    if credited:
        logger.info("Credited %d bar sale(s)", len(credited))
        for telegram_id, bonus, _sale_amount in credited:
            try:
                await send_message(context, telegram_id, bar_bonus_added(bonus, bar_percent))
            except Exception as exc:
                logger.warning("Failed to notify admin %s about bar sale: %s", telegram_id, exc)

    for link in storage.list_links(ROLE_ADMIN):
        if link.user_id == 0:
            continue
        _, error, fixed_amounts = sync_admin_shifts(api, storage, settings, link)
        if error:
            logger.warning("Shift sync failed for %s: %s", link.telegram_id, error)
            continue
        for fixed in fixed_amounts:
            await notify_shift_fixed(context, link.telegram_id, fixed)

    await poll_shift_notifications(context)


async def notify_shift_fixed(
    context: ContextTypes.DEFAULT_TYPE,
    telegram_id: int,
    amount: float,
) -> None:
    try:
        await send_message(context, telegram_id, shift_fixed_added(amount))
    except Exception as exc:
        logger.warning("Failed to notify shift fixed for %s: %s", telegram_id, exc)
