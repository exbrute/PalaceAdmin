from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.config import Settings
from bot.messaging import reply as reply_message
from bot.storage import ROLE_ADMIN, ROLE_DEVELOPER, ROLE_MANAGER, Storage, UserLink
from bot.texts import (
    access_denied,
    developer_only,
    link_langame_first,
    link_langame_for_salary,
    manager_only,
    not_registered,
)


def is_developer(settings: Settings, telegram_id: int) -> bool:
    return telegram_id in settings.developer_telegram_ids


def is_env_manager(settings: Settings, telegram_id: int) -> bool:
    return telegram_id in settings.manager_telegram_ids


def has_manager_access(settings: Settings, storage: Storage, telegram_id: int) -> bool:
    if is_developer(settings, telegram_id):
        return True
    if is_env_manager(settings, telegram_id):
        return True
    return storage.is_staff_manager(telegram_id)


def is_manager(
    link: UserLink | None,
    settings: Settings,
    telegram_id: int,
    storage: Storage | None = None,
) -> bool:
    if storage is not None:
        return has_manager_access(settings, storage, telegram_id)
    return is_developer(settings, telegram_id) or is_env_manager(settings, telegram_id)


def can_use_bot(settings: Settings, storage: Storage, telegram_id: int) -> bool:
    if has_manager_access(settings, storage, telegram_id):
        return True
    link = storage.get_link(telegram_id)
    return link is not None and link.role == ROLE_ADMIN


def list_manager_telegram_ids(settings: Settings, storage: Storage) -> list[int]:
    ids: set[int] = set(settings.manager_telegram_ids)
    ids.update(settings.developer_telegram_ids)
    for member in storage.list_staff_managers():
        ids.add(member.telegram_id)
    return sorted(ids)


def resolve_role(telegram_id: int, settings: Settings, storage: Storage) -> str | None:
    if is_developer(settings, telegram_id):
        return ROLE_DEVELOPER
    if has_manager_access(settings, storage, telegram_id):
        return ROLE_MANAGER
    link = storage.get_link(telegram_id)
    if link and link.role == ROLE_ADMIN:
        return ROLE_ADMIN
    return None


def role_label(role: str | None) -> str:
    if role == ROLE_DEVELOPER:
        return "Разработчик"
    if role == ROLE_MANAGER:
        return "Управляющий"
    if role == ROLE_ADMIN:
        return "Администратор"
    return "Не привязан"


def needs_langame_link(settings: Settings, storage: Storage, telegram_id: int) -> bool:
    link = storage.get_link(telegram_id)
    if link is not None:
        return link.user_id == 0
    return has_manager_access(settings, storage, telegram_id)


async def deny_access(update: Update) -> None:
    await reply_message(update.message, access_denied())


async def require_access(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    settings: Settings = context.application.bot_data["settings"]
    storage: Storage = context.application.bot_data["storage"]
    if can_use_bot(settings, storage, update.effective_user.id):
        return True
    await deny_access(update)
    return False


async def require_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> UserLink | None:
    settings: Settings = context.application.bot_data["settings"]
    storage: Storage = context.application.bot_data["storage"]
    telegram_id = update.effective_user.id
    link = storage.get_link(telegram_id)
    if link:
        return link
    if has_manager_access(settings, storage, telegram_id):
        await reply_message(update.message, link_langame_first())
        return None
    await reply_message(update.message, not_registered())
    return None


async def require_langame_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> UserLink | None:
    link = await require_link(update, context)
    if link is None:
        return None
    if link.user_id == 0:
        await reply_message(update.message, link_langame_for_salary())
        return None
    return link


async def require_manager(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    settings: Settings = context.application.bot_data["settings"]
    storage: Storage = context.application.bot_data["storage"]

    if not has_manager_access(settings, storage, update.effective_user.id):
        await reply_message(update.message, manager_only())
        return False

    return True


async def require_developer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    settings: Settings = context.application.bot_data["settings"]
    if is_developer(settings, update.effective_user.id):
        return True
    await reply_message(update.message, developer_only())
    return False
