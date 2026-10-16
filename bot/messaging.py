from __future__ import annotations

from telegram import Bot, Message
from telegram.constants import ParseMode
from telegram.ext import ContextTypes


def uses_html(text: str) -> bool:
    return "<tg-emoji" in text


async def reply(
    message: Message,
    text: str,
    *,
    reply_markup=None,
) -> None:
    kwargs: dict = {"reply_markup": reply_markup}
    if uses_html(text):
        kwargs["parse_mode"] = ParseMode.HTML
    await message.reply_text(text, **kwargs)


async def send_via_bot(bot: Bot, chat_id: int, text: str, *, reply_markup=None) -> None:
    kwargs: dict = {"chat_id": chat_id, "text": text, "reply_markup": reply_markup}
    if uses_html(text):
        kwargs["parse_mode"] = ParseMode.HTML
    await bot.send_message(**kwargs)


async def send(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
) -> None:
    await send_via_bot(context.bot, chat_id, text)
