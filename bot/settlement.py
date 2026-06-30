from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram.ext import ContextTypes

from bot.messaging import send as send_message
from bot.ledger import get_admin_balance
from bot.pay_period import is_settlement_day
from bot.storage import ROLE_ADMIN, Storage
from bot.texts import settlement_notice

logger = logging.getLogger(__name__)

SETTLEMENT_HOUR = 13
SETTLEMENT_MINUTE = 30


def settle_admin_balance(
    storage: Storage,
    telegram_id: int,
    *,
    cycle_key: str,
    settled_at: str,
) -> float | None:
    if storage.has_balance_settlement(telegram_id, cycle_key):
        return None

    balance = get_admin_balance(storage, telegram_id).balance
    if balance == 0:
        return None

    if storage.add_balance_settlement(
        telegram_id=telegram_id,
        amount=balance,
        cycle_key=cycle_key,
        settled_at=settled_at,
    ) is None:
        return None

    return balance


def settle_all_admin_balances(
    storage: Storage,
    *,
    cycle_key: str,
    settled_at: str,
) -> list[tuple[int, float, str]]:
    settled: list[tuple[int, float, str]] = []
    for link in storage.list_links(ROLE_ADMIN):
        amount = settle_admin_balance(
            storage,
            link.telegram_id,
            cycle_key=cycle_key,
            settled_at=settled_at,
        )
        if amount is None:
            continue
        name = Storage.admin_name(link)
        settled.append((link.telegram_id, amount, name))
    return settled


async def run_scheduled_settlement(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.application.bot_data["settings"]
    storage: Storage = context.application.bot_data["storage"]
    tz = ZoneInfo(settings.settlement_timezone)
    now = datetime.now(tz)

    if not is_settlement_day(now.date()):
        return

    cycle_key = now.strftime("%Y-%m-%d")
    settled_at = now.isoformat(timespec="seconds")
    results = settle_all_admin_balances(
        storage,
        cycle_key=cycle_key,
        settled_at=settled_at,
    )

    if not results:
        logger.info("Balance settlement %s: nothing to reset", cycle_key)
        return

    logger.info(
        "Balance settlement %s: reset %d admin balance(s)",
        cycle_key,
        len(results),
    )

    for telegram_id, amount, name in results:
        text = settlement_notice(amount, now.strftime("%d.%m.%Y %H:%M"))
        try:
            await send_message(context, telegram_id, text)
        except Exception as exc:
            logger.warning("Failed to notify admin %s about settlement: %s", name, exc)
