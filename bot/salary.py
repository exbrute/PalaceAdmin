from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from bot.config import Settings
from bot.langame_api import AdminUser, LangameClient, ProductSale, WorkingShift
from bot.services import get_bar_bonus_percent
from bot.storage import Storage


@dataclass(frozen=True)
class ShiftSalary:
    shift: WorkingShift
    bar_sales_total: float
    bar_bonus: float
    fixed_salary: float
    gross_salary: float
    fines_total: float
    net_salary: float
    sales_count: int


@dataclass(frozen=True)
class PeriodSalary:
    shifts: list[ShiftSalary]
    bar_sales_total: float
    bar_bonus: float
    fixed_salary_total: float
    gross_salary: float
    fines_total: float
    net_salary: float


def _telegram_id_for_langame_user(storage: Storage, langame_user_id: int) -> int | None:
    link = storage.get_link_by_user_id(langame_user_id)
    return link.telegram_id if link else None


def calculate_shift_salary(
    shift: WorkingShift,
    sales: list[ProductSale],
    settings: Settings,
    storage: Storage | None = None,
) -> ShiftSalary:
    shift_sales = [
        sale
        for sale in sales
        if sale.working_shift_id == shift.id and sale.cancel == 0
    ]
    bar_total = sum(sale.price_sale * sale.count for sale in shift_sales)
    percent = (
        get_bar_bonus_percent(storage, settings)
        if storage is not None
        else settings.bar_bonus_percent
    )
    bar_bonus = bar_total * percent / 100
    fixed = settings.fixed_salary
    gross = fixed + bar_bonus

    fines = 0.0
    if storage is not None:
        telegram_id = _telegram_id_for_langame_user(storage, shift.user_id)
        if telegram_id is not None:
            fines = storage.sum_fines(telegram_id, shift.id)

    return ShiftSalary(
        shift=shift,
        bar_sales_total=bar_total,
        bar_bonus=bar_bonus,
        fixed_salary=fixed,
        gross_salary=gross,
        fines_total=fines,
        net_salary=gross - fines,
        sales_count=len(shift_sales),
    )


def calculate_period_salary(
    shifts: list[WorkingShift],
    sales: list[ProductSale],
    settings: Settings,
    storage: Storage | None = None,
) -> PeriodSalary:
    shift_salaries = [
        calculate_shift_salary(shift, sales, settings, storage)
        for shift in shifts
    ]

    bar_total = sum(item.bar_sales_total for item in shift_salaries)
    bar_bonus = sum(item.bar_bonus for item in shift_salaries)
    fixed_total = sum(item.fixed_salary for item in shift_salaries)
    gross = sum(item.gross_salary for item in shift_salaries)
    shift_fines = sum(item.fines_total for item in shift_salaries)

    general_fines = 0.0
    if storage is not None and shifts:
        telegram_id = _telegram_id_for_langame_user(storage, shifts[0].user_id)
        if telegram_id is not None:
            general_fines = sum(
                fine.amount for fine in storage.list_fines(telegram_id, limit=500)
                if fine.shift_id is None
            )

    fines_total = shift_fines + general_fines

    return PeriodSalary(
        shifts=shift_salaries,
        bar_sales_total=bar_total,
        bar_bonus=bar_bonus,
        fixed_salary_total=fixed_total,
        gross_salary=gross,
        fines_total=fines_total,
        net_salary=gross - fines_total,
    )


def shift_date_range(shift: WorkingShift) -> tuple[date | None, date | None]:
    start = shift.date_start.date() if shift.date_start else None
    stop = shift.date_stop.date() if shift.date_stop else None
    if start and not stop:
        stop = date.today()
    return start, stop


def filter_shifts_for_user(
    shifts: list[WorkingShift],
    user_id: int,
    *,
    only_closed: bool = False,
) -> list[WorkingShift]:
    result = [shift for shift in shifts if shift.user_id == user_id]
    if only_closed:
        result = [shift for shift in result if shift.date_stop is not None]
    return sorted(result, key=lambda shift: shift.date_start or datetime.min, reverse=True)


def filter_shifts_by_dates(
    shifts: list[WorkingShift],
    date_from: date,
    date_to: date,
    user_id: int | None = None,
) -> list[WorkingShift]:
    filtered: list[WorkingShift] = []
    for shift in shifts:
        if user_id is not None and shift.user_id != user_id:
            continue
        if not shift.date_start:
            continue
        shift_day = shift.date_start.date()
        if date_from <= shift_day <= date_to:
            filtered.append(shift)
    return sorted(filtered, key=lambda shift: shift.date_start or datetime.min)


def format_money(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ").replace(".", ",") + " ₽"


def format_shift_line(item: ShiftSalary, *, detailed: bool = True) -> str:
    shift = item.shift
    start = shift.date_start.strftime("%d.%m.%Y %H:%M") if shift.date_start else "—"
    stop = shift.date_stop.strftime("%d.%m.%Y %H:%M") if shift.date_stop else "открыта"
    status = "закрыта" if shift.date_stop else "открыта"

    lines = [
        f"Смена #{shift.id} ({status})",
        f"Период: {start} — {stop}",
        f"Продажи бара: {format_money(item.bar_sales_total)} ({item.sales_count} поз.)",
        f"Бонус с бара: {format_money(item.bar_bonus)}",
        f"Фикс: {format_money(item.fixed_salary)}",
        f"Начислено: {format_money(item.gross_salary)}",
    ]

    if detailed and item.fines_total:
        lines.append(f"Штрафы: −{format_money(item.fines_total)}")
        lines.append(f"К выплате: {format_money(item.net_salary)}")
    elif detailed:
        lines.append(f"К выплате: {format_money(item.net_salary)}")

    return "\n".join(lines)


def resolve_langame_user(query: str, users: list[AdminUser]) -> AdminUser | None:
    normalized = query.strip().lower()
    if normalized.isdigit():
        user_id = int(normalized)
        return next((user for user in users if user.id == user_id), None)

    matched = next((user for user in users if user.email.lower() == normalized), None)
    if matched:
        return matched
    return next((user for user in users if normalized in user.email.lower()), None)


def display_name(user: AdminUser | None, fallback_id: int | None = None) -> str:
    if user and user.username:
        return user.username
    if user:
        return user.email
    if fallback_id is not None:
        return f"ID {fallback_id}"
    return "—"
