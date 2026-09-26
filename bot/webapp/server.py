from __future__ import annotations

import logging
from pathlib import Path

from aiohttp import web
from telegram import Bot

from bot.config import Settings
from bot.langame_api import LangameClient
from bot.storage import Storage
from bot.webapp.api import (
    BOT_KEY,
    LANGAME_KEY,
    SETTINGS_KEY,
    STORAGE_KEY,
    api_middleware,
    register_routes,
)

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


@web.middleware
async def no_cache_middleware(request: web.Request, handler) -> web.StreamResponse:
    response = await handler(request)
    if request.path == "/" or request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


async def _index(_: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC_DIR / "index.html")


def create_web_app(
    *,
    settings: Settings,
    storage: Storage,
    langame: LangameClient,
    bot: Bot,
) -> web.Application:
    app = web.Application(middlewares=[no_cache_middleware, api_middleware])
    app[SETTINGS_KEY] = settings
    app[STORAGE_KEY] = storage
    app[LANGAME_KEY] = langame
    app[BOT_KEY] = bot
    register_routes(app)
    app.router.add_get("/", _index)
    app.router.add_static("/static/", STATIC_DIR, append_version=False)
    return app


async def start_web_server(app: web.Application, host: str, port: int) -> web.AppRunner:
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    logger.info("Mini App server listening on http://%s:%s", host, port)
    return runner
