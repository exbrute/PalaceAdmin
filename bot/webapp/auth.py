from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

INIT_DATA_MAX_AGE_SECONDS = 24 * 60 * 60


class InitDataError(Exception):
    pass


@dataclass(frozen=True)
class WebAppUser:
    telegram_id: int
    first_name: str
    last_name: str
    username: str

    @property
    def display_name(self) -> str:
        full = f"{self.first_name} {self.last_name}".strip()
        return full or self.username or str(self.telegram_id)


def _secret_key(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()


def sign_init_data(fields: dict[str, str], bot_token: str) -> str:
    data_check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    return hmac.new(_secret_key(bot_token), data_check_string.encode(), hashlib.sha256).hexdigest()


def validate_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age: int = INIT_DATA_MAX_AGE_SECONDS,
    now: float | None = None,
) -> WebAppUser:
    if not init_data:
        raise InitDataError("Откройте приложение через Telegram")

    fields = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=False))
    received_hash = fields.pop("hash", "")
    if not received_hash:
        raise InitDataError("Нет подписи Telegram")

    expected_hash = sign_init_data(fields, bot_token)
    if not hmac.compare_digest(expected_hash, received_hash):
        raise InitDataError("Неверная подпись Telegram")

    try:
        auth_date = int(fields.get("auth_date", "0"))
    except ValueError as exc:
        raise InitDataError("Некорректная дата авторизации") from exc
    current = time.time() if now is None else now
    if max_age > 0 and current - auth_date > max_age:
        raise InitDataError("Сессия устарела — откройте приложение заново")

    try:
        user = json.loads(fields.get("user", ""))
        telegram_id = int(user["id"])
    except (ValueError, KeyError, TypeError) as exc:
        raise InitDataError("Нет данных пользователя Telegram") from exc

    return WebAppUser(
        telegram_id=telegram_id,
        first_name=str(user.get("first_name") or ""),
        last_name=str(user.get("last_name") or ""),
        username=str(user.get("username") or ""),
    )
