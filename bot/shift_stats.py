from __future__ import annotations

from dataclasses import dataclass

from bot.config import Settings
from bot.langame_api import LangameApiError, LangameClient, WorkingShift, resolve_shift_nal_beznal, shift_total_revenue
from bot.ledger import calculate_shift_stats, sync_shift_by_id
from bot.salary import shift_date_range
from bot.storage import Storage, UserLink


@dataclass(frozen=True)
class ShiftCloseReport:
    bar_revenue: float
    club_revenue: float
    total_revenue: float
    nal_revenue: float
    beznal_revenue: float
    bar_share_percent: float
    cash_in_register: float
    net_salary: float
    fixed: float
    bar_bonus: float
    fines: float


def shift_cash_in_register(shift: WorkingShift) -> float:
    return shift.cash_start + shift.cash_nal - shift.incass - shift.refunds_nal


def shift_club_revenue(total_revenue: float, bar_revenue: float) -> float:
    return max(0.0, total_revenue - bar_revenue)


def build_shift_close_report(
    api: LangameClient,
    storage: Storage,
    settings: Settings,
    link: UserLink,
    shift: WorkingShift,
) -> ShiftCloseReport:
    earning, _, _ = sync_shift_by_id(api, storage, settings, link, shift.id)

    if earning is not None:
        bar_revenue = earning.bar_sales
        bar_bonus = earning.bar_bonus
        fixed = earning.fixed_salary
    else:
        date_from, date_to = shift_date_range(shift)
        sales = []
        if date_from is not None and date_to is not None:
            try:
                sales = api.get_product_sales(date_from=date_from, date_to=date_to)
            except LangameApiError:
                sales = []
        bar_revenue, bar_bonus, fixed, _, _ = calculate_shift_stats(shift, sales, settings, storage)

    fines = storage.sum_fines(link.telegram_id, shift.id)
    net_salary = fixed + bar_bonus - fines
    date_from, date_to = shift_date_range(shift)
    nal_revenue, beznal_revenue = resolve_shift_nal_beznal(
        api, shift, date_from, date_to
    )
    total_revenue = nal_revenue + beznal_revenue
    if total_revenue <= 0:
        total_revenue = shift_total_revenue(shift)
        nal_revenue = max(0.0, shift.cash_nal - shift.refunds_nal)
        beznal_revenue = max(0.0, total_revenue - nal_revenue)
    club_revenue = shift_club_revenue(total_revenue, bar_revenue)
    bar_share_percent = (bar_revenue / total_revenue * 100) if total_revenue > 0 else 0.0
    cash_in_register = shift_cash_in_register(shift)

    return ShiftCloseReport(
        bar_revenue=bar_revenue,
        club_revenue=club_revenue,
        total_revenue=total_revenue,
        nal_revenue=nal_revenue,
        beznal_revenue=beznal_revenue,
        bar_share_percent=bar_share_percent,
        cash_in_register=cash_in_register,
        net_salary=net_salary,
        fixed=fixed,
        bar_bonus=bar_bonus,
        fines=fines,
    )
