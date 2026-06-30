from __future__ import annotations

from telegram import Message
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


async def send(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
) -> None:
    kwargs: dict = {"chat_id": chat_id, "text": text}
    if uses_html(text):
        kwargs["parse_mode"] = ParseMode.HTML
    await context.bot.send_message(**kwargs)
