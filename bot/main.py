from __future__ import annotations

import logging
from datetime import time
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from bot.bar_sales import poll_bar_sales
from bot.config import get_settings
from bot.handlers.manager import bar_percent, cancel_fine, remove_admin
from bot.handlers.router import handle_button, handle_help, handle_start
from bot.langame_api import LangameClient
from bot.settlement import (
    SETTLEMENT_HOUR,
    SETTLEMENT_MINUTE,
    run_scheduled_settlement,
)
from bot.storage import Storage

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def post_init(application: Application) -> None:
    settings = application.bot_data["settings"]
    if application.job_queue is None:
        logger.warning("Job queue unavailable; scheduled balance resets disabled")
        return

    tz = ZoneInfo(settings.settlement_timezone)
    application.job_queue.run_daily(
        run_scheduled_settlement,
        time=time(hour=SETTLEMENT_HOUR, minute=SETTLEMENT_MINUTE, tzinfo=tz),
        name="balance_settlement",
    )
    application.job_queue.run_repeating(
        poll_bar_sales,
        interval=60,
        first=10,
        name="bar_sales_poll",
    )
    logger.info(
        "Balance reset scheduled daily at %02d:%02d (%s), runs on 1st and 16th",
        SETTLEMENT_HOUR,
        SETTLEMENT_MINUTE,
        settings.settlement_timezone,
    )
    logger.info("Bar sales poll scheduled every 60 seconds")


def main() -> None:
    settings = get_settings()
    api = LangameClient(settings)
    storage = Storage(settings.database_path)

    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .build()
    )
    application.bot_data["settings"] = settings
    application.bot_data["api"] = api
    application.bot_data["storage"] = storage

    application.add_handler(CommandHandler("start", handle_start))
    application.add_handler(CommandHandler("help", handle_help))
    application.add_handler(CommandHandler("cancel_fine", cancel_fine))
    application.add_handler(CommandHandler("remove_admin", remove_admin))
    application.add_handler(CommandHandler("bar_percent", bar_percent))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_button))

    logger.info("Bot started")
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    finally:
        api.close()
        storage.close()


if __name__ == "__main__":
    main()
