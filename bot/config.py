from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    langame_api_url: str
    langame_api_token: str
    fixed_salary: float
    fixed_shift_work: float
    fixed_cleaning: float
    shift_standard_hours: float
    bar_bonus_percent: float
    database_path: Path
    manager_telegram_ids: frozenset[int]
    developer_telegram_ids: frozenset[int]
    settlement_timezone: str
    earnings_start_date: date | None


def _parse_date(raw: str) -> date | None:
    text = raw.strip()
    if not text:
        return None
    return date.fromisoformat(text)


def _parse_id_set(raw: str) -> frozenset[int]:
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return frozenset(ids)


def get_settings() -> Settings:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    api_token = os.getenv("LANGAME_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    fixed_salary = float(os.getenv("FIXED_SALARY", "2500"))
    fixed_cleaning = float(os.getenv("FIXED_CLEANING", "500"))
    fixed_shift_work = float(os.getenv("FIXED_SHIFT_WORK", str(fixed_salary - fixed_cleaning)))
    shift_standard_hours = float(os.getenv("SHIFT_STANDARD_HOURS", "12"))

    return Settings(
        telegram_bot_token=token,
        langame_api_url=os.getenv("LANGAME_API_URL", "https://1195.langame.ru/public_api").rstrip("/"),
        langame_api_token=api_token,
        fixed_salary=fixed_salary,
        fixed_shift_work=fixed_shift_work,
        fixed_cleaning=fixed_cleaning,
        shift_standard_hours=shift_standard_hours,
        bar_bonus_percent=float(os.getenv("BAR_BONUS_PERCENT", "20")),
        database_path=Path(os.getenv("DATABASE_PATH", "data/bot.db")),
        manager_telegram_ids=_parse_id_set(os.getenv("MANAGER_TELEGRAM_IDS", "")),
        developer_telegram_ids=_parse_id_set(os.getenv("DEVELOPER_TELEGRAM_IDS", "")),
        settlement_timezone=os.getenv("SETTLEMENT_TIMEZONE", "Europe/Moscow").strip(),
        earnings_start_date=_parse_date(os.getenv("EARNINGS_START_DATE", "")),
    )
