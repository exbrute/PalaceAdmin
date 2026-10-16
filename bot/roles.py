from __future__ import annotations

from bot.config import Settings
from bot.storage import ROLE_ADMIN, ROLE_DEVELOPER, ROLE_MANAGER, Storage, UserLink


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
