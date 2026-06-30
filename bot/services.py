from __future__ import annotations

from datetime import date

from bot.config import Settings
from bot.langame_api import LangameClient, WorkingShift
from bot.storage import Storage

BAR_BONUS_PERCENT_KEY = "bar_bonus_percent"


def format_percent(value: float) -> str:
    rounded = round(value, 2)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:g}"


def get_bar_bonus_percent(storage: Storage, settings: Settings) -> float:
    raw = storage.get_bot_setting(BAR_BONUS_PERCENT_KEY)
    if raw is not None:
        try:
            parsed = float(raw.replace(",", "."))
            if 0 <= parsed <= 100:
                return parsed
        except ValueError:
            pass
    return settings.bar_bonus_percent


def set_bar_bonus_percent(storage: Storage, value: float) -> None:
    if value < 0 or value > 100:
        raise ValueError("Процент должен быть от 0 до 100")
    storage.set_bot_setting(BAR_BONUS_PERCENT_KEY, format_percent(value))


def find_shift(api: LangameClient, shift_id: int) -> WorkingShift | None:
    shifts = api.get_working_shifts()
    return next((item for item in shifts if item.id == shift_id), None)
