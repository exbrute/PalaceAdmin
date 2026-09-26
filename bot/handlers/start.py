from __future__ import annotations

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
    WebAppInfo,
)
from telegram.ext import ContextTypes

from bot.config import Settings
from bot.emojis import e
from bot.messaging import reply as reply_message
from bot.roles import can_use_bot, has_manager_access, is_developer
from bot.services import get_bar_bonus_percent
from bot.storage import Storage
from bot.texts import (
    access_denied,
    open_app_hint,
    webapp_not_configured,
    welcome_admin,
    welcome_developer,
    welcome_guest,
    welcome_manager,
)

OPEN_APP_LABEL = "Открыть Palace Adms"


def build_open_app_markup(settings: Settings) -> InlineKeyboardMarkup | None:
    if not settings.webapp_url:
        return None
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(OPEN_APP_LABEL, web_app=WebAppInfo(url=settings.webapp_url))]
    ])


async def _reply_with_app_button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
) -> None:
    settings: Settings = context.application.bot_data["settings"]
    markup = build_open_app_markup(settings)
    if markup is None:
        text = f"{text}\n\n{webapp_not_configured()}"

    # Clears the legacy reply keyboard left over from the button-based bot.
    cleanup = await update.message.reply_text("⏳", reply_markup=ReplyKeyboardRemove())
    await reply_message(update.message, text, reply_markup=markup)
    try:
        await cleanup.delete()
    except Exception:
        pass


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    storage: Storage = context.application.bot_data["storage"]
    telegram_id = update.effective_user.id

    if not can_use_bot(settings, storage, telegram_id):
        await reply_message(
            update.message,
            f"{access_denied()}\n\n{e('info')} Ваш Telegram ID: {telegram_id}",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    link = storage.get_link(telegram_id)
    if is_developer(settings, telegram_id):
        text = welcome_developer()
    elif has_manager_access(settings, storage, telegram_id):
        text = welcome_manager()
    elif link:
        text = welcome_admin(
            langame_linked=link.user_id != 0,
            bar_bonus_percent=get_bar_bonus_percent(storage, settings),
            fixed_salary=settings.fixed_salary,
        )
    else:
        text = welcome_guest()

    await _reply_with_app_button(update, context, text)


async def handle_other(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    storage: Storage = context.application.bot_data["storage"]
    if not can_use_bot(settings, storage, update.effective_user.id):
        await handle_start(update, context)
        return
    await _reply_with_app_button(update, context, open_app_hint())
