from __future__ import annotations

import logging
from datetime import time
from zoneinfo import ZoneInfo

from telegram import MenuButtonDefault, MenuButtonWebApp, Update, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from bot.bar_sales import poll_bar_sales
from bot.config import get_settings
from bot.handlers.start import OPEN_APP_LABEL, handle_other, handle_start
from bot.langame_api import LangameClient
from bot.settlement import (
    SETTLEMENT_HOUR,
    SETTLEMENT_MINUTE,
    run_scheduled_settlement,
)
from bot.storage import Storage
from bot.webapp.server import create_web_app, start_web_server

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

WEB_RUNNER_KEY = "web_runner"


async def _setup_menu_button(application: Application) -> None:
    settings = application.bot_data["settings"]
    try:
        if settings.webapp_url:
            await application.bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text=OPEN_APP_LABEL,
                    web_app=WebAppInfo(url=settings.webapp_url),
                )
            )
        else:
            await application.bot.set_chat_menu_button(menu_button=MenuButtonDefault())
        await application.bot.delete_my_commands()
    except Exception as exc:
        logger.warning("Failed to configure chat menu button: %s", exc)


async def post_init(application: Application) -> None:
    settings = application.bot_data["settings"]

    web_app = create_web_app(
        settings=settings,
        storage=application.bot_data["storage"],
        langame=application.bot_data["api"],
        bot=application.bot,
    )
    application.bot_data[WEB_RUNNER_KEY] = await start_web_server(
        web_app, settings.webapp_host, settings.webapp_port
    )
    if not settings.webapp_url:
        logger.warning("WEBAPP_URL is not set; the Mini App button will not be shown")
    await _setup_menu_button(application)

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


async def post_shutdown(application: Application) -> None:
    runner = application.bot_data.pop(WEB_RUNNER_KEY, None)
    if runner is not None:
        await runner.cleanup()


def main() -> None:
    settings = get_settings()
    api = LangameClient(settings)
    storage = Storage(settings.database_path)

    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    application.bot_data["settings"] = settings
    application.bot_data["api"] = api
    application.bot_data["storage"] = storage

    application.add_handler(CommandHandler("start", handle_start))
    application.add_handler(MessageHandler(filters.UpdateType.MESSAGE, handle_other))

    logger.info("Bot started")
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    finally:
        api.close()
        storage.close()


if __name__ == "__main__":
    main()
