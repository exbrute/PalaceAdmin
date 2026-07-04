from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx

from bot.config import Settings


class LangameApiError(Exception):
    pass


@dataclass(frozen=True)
class AdminUser:
    id: int
    email: str
    username: str | None


@dataclass(frozen=True)
class WorkingShift:
    id: int
    user_id: int
    club_id: int
    date_start: datetime | None
    date_stop: datetime | None
    cash_start: float = 0.0
    cash_nal: float = 0.0
    cash_beznal: float = 0.0
    refunds_nal: float = 0.0
    refunds_beznal: float = 0.0
    mobile_pay: float = 0.0
    yandex_pay: float = 0.0
    incass: float = 0.0
    middle_check: str | None = None
    close_message: str | None = None


@dataclass(frozen=True)
class ProductSale:
    id: int
    working_shift_id: int
    product_id: int
    product_name: str
    price_sale: float
    count: int
    cancel: int
    date: datetime


@dataclass(frozen=True)
class MoneyTransaction:
    id: int
    working_shift_id: int | None
    session_id: int | None
    balance: float
    cancel: int
    date_update: datetime | None


class LangameClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.Client(
            base_url=settings.langame_api_url,
            headers={"X-Request-Token": settings.langame_api_token},
            timeout=30.0,
        )
        self._product_names_by_id: dict[int, str] | None = None

    def close(self) -> None:
        self._client.close()

    def _ensure_token(self) -> None:
        if not self._settings.langame_api_token:
            raise LangameApiError(
                "LANGAME_API_TOKEN не настроен. Добавьте ключ в /opt/palace-adms/.env на сервере."
            )

    def _get_paginated(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self._ensure_token()
        page = 1
        items: list[dict[str, Any]] = []

        while True:
            query = {"page": page, "page_limit": 100}
            if params:
                query.update(params)

            response = self._client.get(path, params=query)
            if response.status_code == 403:
                raise LangameApiError("Нет доступа к API. Проверьте LANGAME_API_TOKEN.")
            response.raise_for_status()

            payload = response.json()
            if not payload.get("status", False):
                raise LangameApiError("API вернул status=false")

            batch = payload.get("data") or []
            items.extend(batch)

            total_pages = payload.get("total_pages") or 1
            if page >= total_pages:
                break
            page += 1

        return items

    def get_users(self) -> list[AdminUser]:
        self._ensure_token()
        response = self._client.get("/users/list")
        if response.status_code == 403:
            raise LangameApiError("Нет доступа к API. Проверьте LANGAME_API_TOKEN.")
        response.raise_for_status()
        payload = response.json()
        if not payload.get("status", False):
            raise LangameApiError("Не удалось получить список пользователей")

        users: list[AdminUser] = []
        for item in payload.get("data") or []:
            users.append(
                AdminUser(
                    id=int(item["id"]),
                    email=str(item.get("email") or ""),
                    username=item.get("username"),
                )
            )
        return users

    def get_working_shifts(self) -> list[WorkingShift]:
        raw = self._get_paginated("/working_shifts/list")
        shifts: list[WorkingShift] = []
        for item in raw:
            shifts.append(
                WorkingShift(
                    id=int(item["id"]),
                    user_id=int(item["user_id"]),
                    club_id=int(item["list_clubs_id"]),
                    date_start=_parse_datetime(item.get("date_start")),
                    date_stop=_parse_datetime(item.get("date_stop")),
                    cash_start=_float(item.get("start")),
                    cash_nal=_float(item.get("nal")),
                    cash_beznal=_float(item.get("beznal")),
                    refunds_nal=_float(item.get("refunds_nal")),
                    refunds_beznal=_float(item.get("refunds_beznal")),
                    mobile_pay=_float(item.get("mobile_pay")),
                    yandex_pay=_float(item.get("yandex_pay")),
                    incass=_float(item.get("incass")),
                    middle_check=item.get("middle_check"),
                    close_message=item.get("message"),
                )
            )
        return shifts

    def get_product_sales(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[ProductSale]:
        params: dict[str, Any] = {}
        if date_from:
            params["date_from"] = date_from.isoformat()
        if date_to:
            params["date_to"] = date_to.isoformat()

        raw = self._get_paginated("/products/expense", params or None)
        product_names = self._get_product_names_by_id()
        sales: list[ProductSale] = []
        for item in raw:
            price = item.get("price_sale")
            product_id = int(item.get("list_goods_id") or 0)
            sales.append(
                ProductSale(
                    id=int(item["id"]),
                    working_shift_id=int(item["working_shift_id"]),
                    product_id=product_id,
                    product_name=product_names.get(product_id, ""),
                    price_sale=float(price or 0),
                    count=int(item.get("count") or 0),
                    cancel=int(item.get("cancel") or 0),
                    date=_parse_datetime(item.get("date")) or datetime.min,
                )
            )
        return sales

    def _get_product_names_by_id(self) -> dict[int, str]:
        if self._product_names_by_id is not None:
            return self._product_names_by_id

        names: dict[int, str] = {}
        for item in self._get_paginated("/products/list"):
            product_id = int(item.get("id") or 0)
            if product_id <= 0:
                continue
            names[product_id] = str(item.get("name") or "")
        self._product_names_by_id = names
        return names

    def get_transactions(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[MoneyTransaction]:
        params: dict[str, Any] = {}
        if date_from:
            params["date_from"] = date_from.isoformat()
        if date_to:
            params["date_to"] = date_to.isoformat()

        raw = self._get_paginated("/transactions/list", params or None)
        transactions: list[MoneyTransaction] = []
        for item in raw:
            shift_id = item.get("working_shift_id")
            session_id = item.get("session_id")
            transactions.append(
                MoneyTransaction(
                    id=int(item["id"]),
                    working_shift_id=int(shift_id) if shift_id is not None else None,
                    session_id=int(session_id) if session_id is not None else None,
                    balance=float(item.get("balance") or 0),
                    cancel=int(item.get("cancel") or 0),
                    date_update=_parse_datetime(item.get("date_update")),
                )
            )
        return transactions


def _float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d.%m.%Y %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def sale_counts_as_bar(sale: ProductSale) -> bool:
    if sale.cancel != 0:
        return False
    lowered = sale.product_name.lower()
    for keyword in _non_bar_keywords():
        if keyword in lowered:
            return False
    return True


_NON_BAR_KEYWORDS_CACHE: tuple[str, ...] | None = None


def _non_bar_keywords() -> tuple[str, ...]:
    global _NON_BAR_KEYWORDS_CACHE
    if _NON_BAR_KEYWORDS_CACHE is not None:
        return _NON_BAR_KEYWORDS_CACHE

    path = Path(__file__).with_name("non_bar_keywords.txt")
    keywords: list[str] = []
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            text = raw.strip().lower()
            if text and not text.startswith("#"):
                keywords.append(text)
    except FileNotFoundError:
        keywords = ["закупка для сотрудников"]

    _NON_BAR_KEYWORDS_CACHE = tuple(keywords)
    return _NON_BAR_KEYWORDS_CACHE
