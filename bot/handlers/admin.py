from __future__ import annotations

from datetime import date

from telegram import Update
from telegram.ext import ContextTypes

from bot.emojis import e
from bot.keyboards import build_main_keyboard
from bot.langame_api import LangameApiError, LangameClient
from bot.messaging import reply as reply_message
from bot.ledger import (
    format_current_shift_summary,
    format_earning_line,
    format_period_summary,
    get_admin_balance,
    get_period_summary,
    sync_admin_shifts,
    sync_shift_by_id,
)
from bot.pay_period import current_pay_period, today_in_timezone
from bot.roles import has_manager_access, is_developer, require_langame_link, require_link, require_manager, role_label
from bot.salary import format_money, resolve_langame_user
from bot.storage import ROLE_ADMIN, Storage
from bot.texts import langame_linked, no_fines, no_shifts_yet


async def _reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    settings = context.application.bot_data["settings"]
    storage: Storage = context.application.bot_data["storage"]
    keyboard = build_main_keyboard(update.effective_user.id, settings, storage)
    await reply_message(update.message, text, reply_markup=keyboard)


async def _sync_and_reply_error(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    link,
) -> bool:
    settings = context.application.bot_data["settings"]
    api: LangameClient = context.application.bot_data["api"]
    storage: Storage = context.application.bot_data["storage"]
    _, error, _ = sync_admin_shifts(api, storage, settings, link)
    if error:
        await _reply(update, context, error)
        return False
    return True


async def salary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    link = await require_langame_link(update, context)
    if link is None:
        return

    settings = context.application.bot_data["settings"]
    api: LangameClient = context.application.bot_data["api"]
    storage: Storage = context.application.bot_data["storage"]

    if not await _sync_and_reply_error(update, context, link):
        return

    summary = format_current_shift_summary(api, storage, settings, link)
    if summary is None:
        await _reply(update, context, no_shifts_yet())
        return

    await _reply(update, context, summary)


async def shift(update: Update, context: ContextTypes.DEFAULT_TYPE, shift_id: int | None = None) -> None:
    link = await require_langame_link(update, context)
    if link is None:
        return

    if shift_id is None:
        if not context.args or not context.args[0].isdigit():
            await reply_message(update.message,"Укажите id смены")
            return
        shift_id = int(context.args[0])

    settings = context.application.bot_data["settings"]
    api: LangameClient = context.application.bot_data["api"]
    storage: Storage = context.application.bot_data["storage"]

    earning, error, _fixed = sync_shift_by_id(api, storage, settings, link, shift_id)
    if error:
        await _reply(update, context, error)
        return
    if earning is None:
        await _reply(update, context, f"{e('cancel')} Смена #{shift_id} не найдена")
        return

    await _reply(update, context, format_earning_line(storage, earning, settings))


async def _reply_period_salary(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    date_from: date,
    date_to: date,
    title: str,
    *,
    next_payout: date | None = None,
) -> None:
    link = await require_langame_link(update, context)
    if link is None:
        return

    settings = context.application.bot_data["settings"]
    api: LangameClient = context.application.bot_data["api"]
    storage: Storage = context.application.bot_data["storage"]

    if not await _sync_and_reply_error(update, context, link):
        return

    summary = get_period_summary(storage, link.telegram_id, date_from, date_to)
    if not summary.earnings and summary.gross_earned < 0.01:
        await _reply(update, context, f"{title}: начислений за период пока нет")
        return

    balance = get_admin_balance(storage, link.telegram_id)
    await _reply(
        update,
        context,
        format_period_summary(
            storage,
            summary,
            settings,
            title=title,
            date_from=date_from,
            date_to=date_to,
            balance=balance,
            next_payout=next_payout,
        ),
    )


async def half_month(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.application.bot_data["settings"]
    today = today_in_timezone(settings.settlement_timezone)
    period = current_pay_period(today)
    await _reply_period_salary(
        update,
        context,
        period.date_from,
        period.date_to,
        period.title,
        next_payout=period.next_payout,
    )


async def myfines(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    link = await require_link(update, context)
    if link is None:
        return

    storage: Storage = context.application.bot_data["storage"]
    fines = storage.list_fines(link.telegram_id)

    if not fines:
        await _reply(update, context, no_fines())
        return

    lines = [f"{e('warning')} Ваши штрафы:"]
    for fine in fines[:15]:
        shift_part = f", смена #{fine.shift_id}" if fine.shift_id else ""
        lines.append(
            f"#{fine.id}: −{format_money(fine.amount)}{shift_part}\n"
            f"{fine.reason}\n"
            f"{fine.created_at[:16]}"
        )
    await _reply(update, context, "\n\n".join(lines))


async def me(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.application.bot_data["settings"]
    storage: Storage = context.application.bot_data["storage"]
    telegram_id = update.effective_user.id

    if is_developer(settings, telegram_id):
        await reply_message(update.message,
            f"Роль: Разработчик\nTelegram ID: {telegram_id}"
        )
        return

    if has_manager_access(settings, storage, telegram_id):
        await reply_message(update.message,
            f"Роль: Управляющий\nTelegram ID: {telegram_id}"
        )
        return

    link = storage.get_link(telegram_id)
    if not link:
        await reply_message(update.message,"Вы не зарегистрированы.")
        return

    balance = get_admin_balance(storage, telegram_id)
    name = link.username or "—"
    langame = "привязан" if link.user_id else "не привязан — нажмите «Привязать аккаунт»"
    await _reply(
        update,
        context,
        f"Роль: {role_label(link.role)}\n"
        f"Имя: {name}\n"
        f"Telegram ID: {link.telegram_id}\n"
        f"LANGAME: {langame}\n"
        f"Email: {link.email if link.user_id else '—'}\n\n"
        f"{e('money_bag')} Баланс в боте: {format_money(balance.balance)}\n"
        f"Смен: {balance.shifts_count}, начислено: {format_money(balance.gross_earned)}",
    )


async def link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = context.application.bot_data["settings"]
    api: LangameClient = context.application.bot_data["api"]
    storage: Storage = context.application.bot_data["storage"]
    telegram_id = update.effective_user.id

    if not context.args:
        await reply_message(update.message,"Укажите email: /link admin@example.com")
        return

    existing = storage.get_link(telegram_id)
    if not existing and not has_manager_access(settings, storage, telegram_id):
        await reply_message(update.message,"Вы не зарегистрированы. Обратитесь к управляющему.")
        return

    query = context.args[0].strip().lower()
    try:
        users = api.get_users()
    except LangameApiError as exc:
        await reply_message(update.message,str(exc))
        return

    matched = resolve_langame_user(query, users)
    if not matched:
        await reply_message(update.message,"Администратор не найден. Проверьте email или id.")
        return

    if existing:
        storage.attach_langame(
            telegram_id=telegram_id,
            user_id=matched.id,
            email=matched.email,
            langame_username=matched.username,
        )
        name = existing.username or matched.username or matched.email
    else:
        storage.link_admin(
            telegram_id=telegram_id,
            user_id=matched.id,
            email=matched.email,
            username=matched.username or matched.email,
            role=ROLE_ADMIN,
        )
        name = matched.username or matched.email

    synced, sync_error, _ = sync_admin_shifts(api, storage, settings, storage.get_link(telegram_id))

    keyboard = build_main_keyboard(telegram_id, settings, storage)
    await reply_message(update.message,
        langame_linked(name, matched.id, synced=synced, sync_error=sync_error),
        reply_markup=keyboard,
    )


async def admins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_manager(update, context):
        return

    storage: Storage = context.application.bot_data["storage"]
    links = storage.list_links(ROLE_ADMIN)

    if not links:
        await reply_message(update.message,"Администраторы ещё не добавлены.")
        return

    lines = ["Администраторы бота:"]
    for link in links:
        name = link.username or "—"
        balance = get_admin_balance(storage, link.telegram_id)
        langame = f", LANGAME id: {link.user_id}" if link.user_id else ", LANGAME не привязан"
        lines.append(
            f"• {name} — TG: {link.telegram_id}{langame}\n"
            f"  Баланс: {format_money(balance.balance)}"
        )

    await reply_message(update.message,"\n".join(lines))
