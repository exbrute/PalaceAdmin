from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from bot.emojis import e
from bot.config import Settings
from bot.langame_api import LangameApiError, LangameClient, ProductSale, WorkingShift, resolve_shift_nal_beznal, sale_counts_as_bar
from bot.salary import (
    filter_shifts_for_user,
    format_money,
    shift_date_range,
)
from bot.services import format_percent, get_bar_bonus_percent
from bot.shift_fixed import (
    FixedShare,
    club_shift_key,
    distribute_club_shift_fixed,
    estimate_open_shift_fixed,
)
from bot.storage import ShiftEarning, Storage, UserLink


@dataclass(frozen=True)
class AdminBalance:
    telegram_id: int
    shifts_count: int
    shift_earned: float
    bar_bonus_instant: float
    gross_earned: float
    fines_total: float
    settled_total: float
    balance: float


@dataclass(frozen=True)
class BotPeriodSummary:
    earnings: list[ShiftEarning]
    gross_earned: float
    bar_sales_total: float
    bar_bonus_total: float
    bar_bonus_instant: float
    fixed_total: float
    fines_total: float
    net_amount: float


def shift_eligible_for_earnings(shift: WorkingShift, settings: Settings) -> bool:
    if settings.earnings_start_date is None:
        return True
    if not shift.date_start:
        return False
    return shift.date_start.date() >= settings.earnings_start_date


def calculate_shift_bar_stats(
    shift: WorkingShift,
    sales: list[ProductSale],
    settings: Settings,
    storage: Storage,
) -> tuple[float, float, int]:
    shift_sales = [
        sale
        for sale in sales
        if sale.working_shift_id == shift.id and sale_counts_as_bar(sale)
    ]
    bar_total = sum(sale.price_sale * sale.count for sale in shift_sales)
    bar_bonus = bar_total * get_bar_bonus_percent(storage, settings) / 100
    return bar_total, bar_bonus, len(shift_sales)


def calculate_shift_stats(
    shift: WorkingShift,
    sales: list[ProductSale],
    settings: Settings,
    storage: Storage,
    fixed_share: FixedShare | None = None,
) -> tuple[float, float, float, float, int]:
    bar_total, bar_bonus, sales_count = calculate_shift_bar_stats(
        shift, sales, settings, storage
    )
    if fixed_share is None:
        shares = distribute_club_shift_fixed([shift], settings)
        fixed_share = shares.get(shift.id, FixedShare(shift.id, 0.0, 0.0, 0.0))
    fixed = fixed_share.fixed_total
    gross = fixed + bar_bonus
    return bar_total, bar_bonus, fixed, gross, sales_count


def _format_hours(hours: float) -> str:
    if hours == int(hours):
        return str(int(hours))
    text = f"{hours:.2f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def format_fixed_breakdown(
    settings: Settings,
    *,
    worked_hours: float,
    fixed_work: float,
    fixed_cleaning: float,
    fixed_total: float,
) -> str:
    hourly = settings.fixed_shift_work / settings.shift_standard_hours
    parts: list[str] = []
    if fixed_work > 0:
        parts.append(
            f"{_format_hours(worked_hours)} ч × {format_money(hourly)} = {format_money(fixed_work)}"
        )
    if fixed_cleaning > 0:
        parts.append(f"уборка {format_money(fixed_cleaning)}")
    if parts:
        return f"{format_money(fixed_total)} ({' + '.join(parts)})"
    return format_money(fixed_total)


def _linked_club_group(
    all_shifts: list[WorkingShift],
    storage: Storage,
    settings: Settings,
    shift: WorkingShift,
) -> list[WorkingShift]:
    key = club_shift_key(shift, settings)
    if key is None:
        return []
    group = [
        item
        for item in all_shifts
        if club_shift_key(item, settings) == key
        and storage.get_link_by_user_id(item.user_id) is not None
    ]
    return sorted(group, key=lambda item: item.date_start or datetime.min)


def _fetch_shift_sales(
    api: LangameClient,
    shift: WorkingShift,
) -> tuple[list[ProductSale], str | None]:
    date_from, date_to = shift_date_range(shift)
    try:
        sales = api.get_product_sales(date_from=date_from, date_to=date_to)
    except LangameApiError as exc:
        return [], str(exc)
    return sales, None


def recalculate_club_shift_group(
    api: LangameClient,
    storage: Storage,
    settings: Settings,
    all_shifts: list[WorkingShift],
    club_key: str,
) -> tuple[list[int], str | None]:
    group = [
        shift
        for shift in all_shifts
        if club_shift_key(shift, settings) == club_key
        and shift.date_stop is not None
        and shift_eligible_for_earnings(shift, settings)
        and storage.get_link_by_user_id(shift.user_id) is not None
    ]
    if not group:
        return [], None

    shares = distribute_club_shift_fixed(group, settings)
    newly_synced: list[int] = []

    for shift in group:
        link = storage.get_link_by_user_id(shift.user_id)
        if link is None:
            continue

        sales, error = _fetch_shift_sales(api, shift)
        if error:
            return newly_synced, error

        bar_total, bar_bonus, sales_count = calculate_shift_bar_stats(
            shift, sales, settings, storage
        )
        share = shares.get(shift.id, FixedShare(shift.id, 0.0, 0.0, 0.0))
        fixed = share.fixed_total
        gross = fixed + bar_bonus
        was_new = storage.upsert_shift_earning(
            shift_id=shift.id,
            telegram_id=link.telegram_id,
            langame_user_id=link.user_id,
            shift_start=shift.date_start.isoformat(timespec="seconds") if shift.date_start else None,
            shift_stop=shift.date_stop.isoformat(timespec="seconds") if shift.date_stop else None,
            bar_sales=bar_total,
            bar_bonus=bar_bonus,
            fixed_salary=fixed,
            gross_amount=gross,
            sales_count=sales_count,
            worked_hours=share.worked_hours,
            fixed_work=share.fixed_work,
            fixed_cleaning=share.fixed_cleaning,
            club_shift_key=club_key,
        )
        if was_new:
            newly_synced.append(shift.id)

    return newly_synced, None


def sync_admin_shifts(
    api: LangameClient,
    storage: Storage,
    settings: Settings,
    link: UserLink,
) -> tuple[int, str | None, list[int]]:
    if link.user_id == 0:
        return 0, f"{e('link')} LANGAME не привязан. Попросите управляющего указать LANGAME id.", []

    try:
        all_shifts = api.get_working_shifts()
    except LangameApiError as exc:
        return 0, str(exc), []

    user_shifts = filter_shifts_for_user(all_shifts, link.user_id, only_closed=True)
    keys_to_process: set[str] = set()
    for shift in user_shifts:
        if not shift_eligible_for_earnings(shift, settings):
            continue
        if storage.has_shift_earning(shift.id):
            continue
        key = club_shift_key(shift, settings)
        if key:
            keys_to_process.add(key)

    synced = 0
    synced_shift_ids: list[int] = []
    for club_key in sorted(keys_to_process):
        new_ids, error = recalculate_club_shift_group(
            api, storage, settings, all_shifts, club_key
        )
        if error:
            return synced, error, synced_shift_ids
        for shift_id in new_ids:
            earning = storage.get_shift_earning(shift_id)
            if earning and earning.telegram_id == link.telegram_id:
                synced += 1
                synced_shift_ids.append(shift_id)

    return synced, None, synced_shift_ids


def sync_shift_by_id(
    api: LangameClient,
    storage: Storage,
    settings: Settings,
    link: UserLink,
    shift_id: int,
) -> tuple[ShiftEarning | None, str | None, float | None]:
    if link.user_id == 0:
        return None, f"{e('link')} LANGAME не привязан. Попросите управляющего указать LANGAME id.", None

    try:
        all_shifts = api.get_working_shifts()
    except LangameApiError as exc:
        return None, str(exc), None

    shift = next((item for item in all_shifts if item.id == shift_id), None)
    if not shift:
        return None, f"{e('cancel')} Смена #{shift_id} не найдена в LANGAME", None
    if shift.user_id != link.user_id:
        return None, f"{e('prohibited')} Эта смена принадлежит другому администратору", None
    if shift.date_stop is None:
        return None, f"{e('refresh')} Смена ещё не закрыта — фикс начислится после закрытия", None
    if not shift_eligible_for_earnings(shift, settings):
        return None, f"{e('cancel')} Смена до {settings.earnings_start_date.strftime('%d.%m.%Y')} не учитывается", None

    club_key = club_shift_key(shift, settings)
    if club_key is None:
        return None, f"{e('cancel')} Не удалось определить клубную смену", None

    _, error = recalculate_club_shift_group(api, storage, settings, all_shifts, club_key)
    if error:
        return None, error, None

    earning = storage.get_shift_earning(shift_id)
    fixed = earning.fixed_salary if earning else None
    return earning, None, fixed


def sync_all_admins(
    api: LangameClient,
    storage: Storage,
    settings: Settings,
) -> tuple[int, str | None]:
    total = 0
    for link in storage.list_links("admin"):
        if link.user_id == 0:
            continue
        count, error, _ = sync_admin_shifts(api, storage, settings, link)
        if error:
            return total, error
        total += count
    return total, None


def get_admin_balance(storage: Storage, telegram_id: int) -> AdminBalance:
    shift_earned = storage.sum_shift_earnings(telegram_id)
    bar_instant = storage.sum_unsettled_bar_sale_credits(telegram_id)
    fines = storage.sum_fines(telegram_id)
    settled = storage.sum_settlements(telegram_id)
    count = storage.count_shift_earnings(telegram_id)
    gross = shift_earned + bar_instant
    return AdminBalance(
        telegram_id=telegram_id,
        shifts_count=count,
        shift_earned=shift_earned,
        bar_bonus_instant=bar_instant,
        gross_earned=gross,
        fines_total=fines,
        settled_total=settled,
        balance=gross - fines - settled,
    )


def get_period_summary(
    storage: Storage,
    telegram_id: int,
    date_from: date,
    date_to: date,
) -> BotPeriodSummary:
    earnings = storage.list_shift_earnings(telegram_id, date_from, date_to)
    shift_gross = sum(item.gross_amount for item in earnings)
    bar_sales = sum(item.bar_sales for item in earnings)
    bar_bonus_shift = sum(item.bar_bonus for item in earnings)
    bar_instant = storage.sum_unsettled_bar_sale_credits(telegram_id, date_from, date_to)
    fixed = sum(item.fixed_salary for item in earnings)
    fines = storage.sum_fines_between(telegram_id, date_from, date_to)
    gross = shift_gross + bar_instant
    return BotPeriodSummary(
        earnings=earnings,
        gross_earned=gross,
        bar_sales_total=bar_sales,
        bar_bonus_total=bar_bonus_shift + bar_instant,
        bar_bonus_instant=bar_instant,
        fixed_total=fixed,
        fines_total=fines,
        net_amount=gross - fines,
    )


def earning_net(storage: Storage, earning: ShiftEarning) -> float:
    fines = storage.sum_fines(earning.telegram_id, earning.shift_id)
    return earning.gross_amount - fines


def format_earning_line(
    storage: Storage,
    earning: ShiftEarning,
    settings: Settings,
) -> str:
    start = "—"
    stop = "—"
    if earning.shift_start:
        start = datetime.fromisoformat(earning.shift_start).strftime("%d.%m.%Y %H:%M")
    if earning.shift_stop:
        stop = datetime.fromisoformat(earning.shift_stop).strftime("%d.%m.%Y %H:%M")

    fines = storage.sum_fines(earning.telegram_id, earning.shift_id)
    net = earning.gross_amount - fines
    bar_percent = format_percent(get_bar_bonus_percent(storage, settings))
    fixed_text = format_fixed_breakdown(
        settings,
        worked_hours=earning.worked_hours,
        fixed_work=earning.fixed_work,
        fixed_cleaning=earning.fixed_cleaning,
        fixed_total=earning.fixed_salary,
    )

    lines = [
        f"{e('gear')} Смена #{earning.shift_id}",
        f"{e('date')} Период: {start} — {stop}",
        f"{e('burger')} Продажи бара: {format_money(earning.bar_sales)} ({earning.sales_count} поз.)",
        f"{e('money')} {bar_percent}% с бара: {format_money(earning.bar_bonus)} — начисляется сразу",
        f"{e('check')} Фикс за смену: {fixed_text}",
    ]
    if fines:
        lines.append(f"{e('warning')} Штрафы: −{format_money(fines)}")
    lines.append(f"{e('money_bag')} К выплате за смену: {format_money(net)}")
    return "\n".join(lines)


def find_open_shift(api: LangameClient, user_id: int) -> WorkingShift | None:
    try:
        shifts = api.get_working_shifts()
    except LangameApiError:
        return None
    for shift in filter_shifts_for_user(shifts, user_id, only_closed=False):
        if shift.date_stop is None:
            return shift
    return None


def find_open_shifts_for_linked_admins(
    api: LangameClient,
    storage: Storage,
) -> list[tuple[WorkingShift, UserLink]]:
    try:
        shifts = api.get_working_shifts()
    except LangameApiError:
        return []

    open_shifts: list[tuple[WorkingShift, UserLink]] = []
    for shift in shifts:
        if shift.date_stop is not None:
            continue
        link = storage.get_link_by_user_id(shift.user_id)
        if link is None or link.user_id == 0:
            continue
        open_shifts.append((shift, link))

    open_shifts.sort(
        key=lambda item: item[0].date_start or datetime.min,
        reverse=True,
    )
    return open_shifts


def format_manager_current_shift_summary(
    api: LangameClient,
    storage: Storage,
    settings: Settings,
) -> str | None:
    open_shifts = find_open_shifts_for_linked_admins(api, storage)
    if not open_shifts:
        return None

    sections: list[str] = []
    for shift, link in open_shifts:
        body = format_open_shift_line(
            api, storage, settings, link, shift, include_revenue_share=True
        )
        if body is None:
            continue
        admin_name = Storage.admin_name(link)
        sections.append(f"{e('person')} Админ на смене: {admin_name}\n\n{body}")

    return "\n\n".join(sections) if sections else None


def format_open_shift_line(
    api: LangameClient,
    storage: Storage,
    settings: Settings,
    link: UserLink,
    shift: WorkingShift,
    *,
    include_revenue_share: bool = False,
) -> str | None:
    try:
        all_shifts = api.get_working_shifts()
    except LangameApiError:
        all_shifts = [shift]

    date_from, date_to = shift_date_range(shift)
    sales: list[ProductSale] = []
    if date_from is not None and date_to is not None:
        try:
            sales = api.get_product_sales(date_from=date_from, date_to=date_to)
        except LangameApiError:
            sales = []

    bar_total, bar_bonus, sales_count = calculate_shift_bar_stats(
        shift, sales, settings, storage
    )
    group = _linked_club_group(all_shifts, storage, settings, shift)
    is_first_opener = bool(group) and group[0].id == shift.id
    fixed_share = estimate_open_shift_fixed(
        shift, settings=settings, is_first_opener=is_first_opener
    )
    fixed_text = format_fixed_breakdown(
        settings,
        worked_hours=fixed_share.worked_hours,
        fixed_work=fixed_share.fixed_work,
        fixed_cleaning=fixed_share.fixed_cleaning,
        fixed_total=fixed_share.fixed_total,
    )
    fines = storage.sum_fines(link.telegram_id, shift.id)
    bar_percent = format_percent(get_bar_bonus_percent(storage, settings))

    start = "—"
    if shift.date_start:
        start = shift.date_start.strftime("%d.%m.%Y %H:%M")

    net = bar_bonus + fixed_share.fixed_total - fines
    lines = [
        f"{e('check')} Текущая смена (открыта)",
        "",
        f"{e('gear')} Смена #{shift.id}",
        f"{e('date')} Начало: {start}",
        f"{e('burger')} Продажи бара: {format_money(bar_total)} ({sales_count} поз.)",
    ]
    if include_revenue_share:
        nal, beznal = resolve_shift_nal_beznal(api, shift, date_from, date_to)
        total_revenue = nal + beznal
        if total_revenue > 0:
            bar_share = bar_total / total_revenue * 100
            lines.extend([
                f"{e('money')} Нал: {format_money(nal)}",
                f"{e('card')} Безнал: {format_money(beznal)}",
                f"{e('chart_up')} Общая выручка: {format_money(total_revenue)}",
                f"{e('chart')} Бар от выручки: {format_percent(bar_share)}%",
            ])
        else:
            lines.append(f"{e('chart')} Бар от выручки: — (выручка пока 0 ₽)")
    lines.extend([
        f"{e('money')} {bar_percent}% с бара: {format_money(bar_bonus)} — начисляется сразу",
        f"{e('refresh')} Фикс (ориентир): {fixed_text} — после закрытия",
    ])
    if len(group) > 1:
        lines.append(f"{e('info')} В клубной смене {len(group)} админов — фикс пересчитается по часам")
    if fines:
        lines.append(f"{e('warning')} Штрафы: −{format_money(fines)}")
    lines.append(f"{e('money_bag')} Ожидаемая выплата за смену: {format_money(net)}")
    return "\n".join(lines)


def format_current_shift_summary(
    api: LangameClient,
    storage: Storage,
    settings: Settings,
    link: UserLink,
) -> str | None:
    open_shift = find_open_shift(api, link.user_id)
    if open_shift is not None:
        return format_open_shift_line(api, storage, settings, link, open_shift)

    earnings = storage.list_shift_earnings(link.telegram_id, limit=1)
    if not earnings:
        return None

    return (
        f"{e('chart')} Последняя закрытая смена:\n\n"
        + format_earning_line(storage, earnings[0], settings)
    )


def format_period_summary(
    storage: Storage,
    summary: BotPeriodSummary,
    settings: Settings,
    *,
    title: str,
    date_from: date,
    date_to: date,
    balance: AdminBalance | None = None,
    next_payout: date | None = None,
) -> str:
    bar_percent = format_percent(get_bar_bonus_percent(storage, settings))
    lines = [
        title,
        f"{e('date')} Период: {date_from.strftime('%d.%m.%Y')} — {date_to.strftime('%d.%m.%Y')}",
    ]
    if next_payout is not None:
        lines.append(f"{e('money')} Выплата: {next_payout.strftime('%d.%m.%Y')}")
    lines.extend([
        f"{e('gear')} Смен: {len(summary.earnings)}",
        f"{e('burger')} Продажи бара: {format_money(summary.bar_sales_total)}",
        f"{e('money')} {bar_percent}% с бара: {format_money(summary.bar_bonus_total)}",
        f"{e('check')} Фикс: {format_money(summary.fixed_total)}",
        f"{e('chart_up')} Начислено: {format_money(summary.gross_earned)}",
    ])
    if summary.fines_total:
        lines.append(f"{e('warning')} Штрафы: −{format_money(summary.fines_total)}")
    lines.append(f"{e('money_bag')} Итого за период: {format_money(summary.net_amount)}")
    if balance is not None:
        lines.extend([
            "",
            f"{e('card')} Баланс в боте: {format_money(balance.balance)}",
            f"   {e('burger')} с бара сразу: {format_money(balance.bar_bonus_instant)}",
            f"   {e('check')} за смены: {format_money(balance.shift_earned)} ({balance.shifts_count} смен)",
            f"   {e('warning')} штрафы: −{format_money(balance.fines_total)}",
            f"   {e('money')} выплачено: {format_money(balance.settled_total)}",
        ])
    if len(summary.earnings) <= 5:
        lines.append("")
        lines.extend(format_earning_line(storage, item, settings) for item in summary.earnings)
    return "\n\n".join(lines)
