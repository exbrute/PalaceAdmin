from __future__ import annotations

import inspect

from telegram import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove

from bot.config import Settings
from bot.emojis import FALLBACK, icon_id
from bot.roles import can_use_bot, has_manager_access, is_developer
from bot.storage import Storage

BTN_HOME = "Меню"
BTN_CANCEL = "Отмена"
BTN_HELP = "Помощь"
BTN_SALARY = "Текущая смена"
BTN_HALF_MONTH = "За полмесяца"
BTN_NET = "К выплате"
BTN_MY_FINES = "Мои штрафы"
BTN_PROFILE = "Профиль"
BTN_LINK = "Привязать аккаунт"
BTN_ADD_ADMIN = "Добавить админа"
BTN_ADD_MANAGER = "Добавить управляющего"
BTN_TEAM = "Команда"
BTN_PAYROLL = "Ведомость"
BTN_LEADERBOARD = "Рейтинг бара"
BTN_BAR_PERCENT = "% бара"
BTN_BROADCAST = "Рассылка"
BTN_FINE = "Штраф"
BTN_REMOVE_FINE = "Убрать штраф"
BTN_FINES_ALL = "Все штрафы"
BTN_REMOVE_ADMIN = "Убрать админа"
BTN_ADMIN_CARD = "Карточка админа"
BTN_HALF_MONTH_TEST = "Тест полмесяца"
BTN_SHIFT_REPORT = "Отчёт смены"

ADMIN_BUTTONS = {
    BTN_SALARY,
    BTN_HALF_MONTH,
    BTN_NET,
    BTN_MY_FINES,
    BTN_PROFILE,
    BTN_LINK,
    BTN_HELP,
    BTN_HOME,
    BTN_CANCEL,
}

MANAGER_BUTTONS = ADMIN_BUTTONS | {
    BTN_ADD_ADMIN,
    BTN_REMOVE_ADMIN,
    BTN_TEAM,
    BTN_PAYROLL,
    BTN_LEADERBOARD,
    BTN_BAR_PERCENT,
    BTN_BROADCAST,
    BTN_FINE,
    BTN_REMOVE_FINE,
    BTN_FINES_ALL,
    BTN_ADMIN_CARD,
    BTN_HALF_MONTH_TEST,
    BTN_SHIFT_REPORT,
}

STATE_LINK = "link"
STATE_SHIFT_ID = "shift_id"
STATE_ADMIN_QUERY = "admin_query"
STATE_SHIFT_REPORT = "shift_report"
STATE_FINE_ADMIN = "fine_admin"
STATE_FINE_AMOUNT = "fine_amount"
STATE_FINE_REASON = "fine_reason"
STATE_BROADCAST = "broadcast"
STATE_BAR_PERCENT = "bar_percent"
STATE_ADD_ADMIN_NAME = "add_admin_name"
STATE_ADD_ADMIN_TG = "add_admin_tg"
STATE_ADD_MANAGER_NAME = "add_manager_name"
STATE_ADD_MANAGER_TG = "add_manager_tg"
STATE_REMOVE_FINE_ID = "remove_fine_id"
STATE_REMOVE_ADMIN_QUERY = "remove_admin_query"


_SUPPORTS_ICON = "icon_custom_emoji_id" in inspect.signature(KeyboardButton.__init__).parameters


def _btn(label: str, icon: str) -> KeyboardButton:
    if _SUPPORTS_ICON:
        return KeyboardButton(text=label, icon_custom_emoji_id=icon_id(icon))
    emoji = FALLBACK.get(icon, "")
    text = f"{emoji} {label}" if emoji else label
    return KeyboardButton(text=text)


def normalize_button_text(text: str) -> str:
    cleaned = text.strip()
    if _SUPPORTS_ICON:
        return cleaned
    for emoji in FALLBACK.values():
        prefix = f"{emoji} "
        if cleaned.startswith(prefix):
            return cleaned[len(prefix):]
    return cleaned


ALL_MENU_BUTTONS = frozenset({
    BTN_HOME,
    BTN_HELP,
    BTN_SALARY,
    BTN_HALF_MONTH,
    BTN_NET,
    BTN_MY_FINES,
    BTN_PROFILE,
    BTN_LINK,
    BTN_ADD_ADMIN,
    BTN_ADD_MANAGER,
    BTN_TEAM,
    BTN_PAYROLL,
    BTN_LEADERBOARD,
    BTN_BAR_PERCENT,
    BTN_BROADCAST,
    BTN_FINE,
    BTN_REMOVE_FINE,
    BTN_FINES_ALL,
    BTN_ADMIN_CARD,
    BTN_HALF_MONTH_TEST,
    BTN_SHIFT_REPORT,
    BTN_REMOVE_ADMIN,
})


def match_button(text: str) -> str | None:
    normalized = normalize_button_text(text)
    for button in ALL_MENU_BUTTONS:
        if normalize_button_text(button) == normalized:
            return button
    return None


def clear_state(context) -> None:
    context.user_data.pop("state", None)
    context.user_data.pop("draft", None)


def get_draft(context) -> dict:
    return context.user_data.setdefault("draft", {})


def build_main_keyboard(
    telegram_id: int,
    settings: Settings,
    storage: Storage,
) -> ReplyKeyboardMarkup | ReplyKeyboardRemove:
    if not can_use_bot(settings, storage, telegram_id):
        return ReplyKeyboardRemove()

    manager = has_manager_access(settings, storage, telegram_id)
    developer = is_developer(settings, telegram_id)

    rows = [
        [_btn(BTN_SALARY, "money_bag"), _btn(BTN_HALF_MONTH, "date")],
        [_btn(BTN_NET, "card"), _btn(BTN_MY_FINES, "warning")],
        [_btn(BTN_PROFILE, "person"), _btn(BTN_LINK, "link")],
    ]

    if manager:
        manager_rows = [
            [_btn(BTN_ADD_ADMIN, "plus"), _btn(BTN_REMOVE_ADMIN, "prohibited")],
            [_btn(BTN_TEAM, "people"), _btn(BTN_ADMIN_CARD, "magnifier")],
            [_btn(BTN_PAYROLL, "chart"), _btn(BTN_LEADERBOARD, "chart_up")],
            [_btn(BTN_BAR_PERCENT, "burger"), _btn(BTN_BROADCAST, "megaphone")],
            [_btn(BTN_FINE, "label"), _btn(BTN_REMOVE_FINE, "trash")],
            [_btn(BTN_FINES_ALL, "folder"), _btn(BTN_SHIFT_REPORT, "page")],
            [_btn(BTN_HALF_MONTH_TEST, "test")],
        ]
        if developer:
            manager_rows.insert(0, [_btn(BTN_ADD_MANAGER, "person")])
        rows.extend(manager_rows)

    rows.append([_btn(BTN_HELP, "help"), _btn(BTN_HOME, "home")])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def build_cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[_btn(BTN_CANCEL, "cancel")]], resize_keyboard=True)
