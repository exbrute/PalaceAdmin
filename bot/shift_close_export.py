from __future__ import annotations

import csv
import re
from collections import defaultdict
from dataclasses import dataclass
from io import StringIO

from bot.langame_api import LangameClient, ProductSale, WorkingShift, sale_counts_as_bar
from bot.salary import format_money, shift_date_range
from bot.services import format_percent


@dataclass(frozen=True)
class BarProductRow:
    product_name: str
    count: int
    sale_amount: float
    bonus_amount: float
    counts_as_bar: bool


def _csv_money(value: float) -> str:
    return format_money(value).replace("\u00a0", " ").replace("₽", "").strip()


def _safe_filename_part(text: str) -> str:
    cleaned = re.sub(r"[^\w\-]+", "_", text.strip(), flags=re.UNICODE)
    return cleaned.strip("_") or "admin"


def collect_shift_bar_rows(
    sales: list[ProductSale],
    shift_id: int,
    bar_bonus_percent: float,
) -> list[BarProductRow]:
    grouped: dict[tuple[str, bool], tuple[int, float]] = defaultdict(lambda: (0, 0.0))
    for sale in sales:
        if sale.working_shift_id != shift_id or sale.cancel != 0:
            continue
        is_bar = sale_counts_as_bar(sale)
        amount = sale.price_sale * sale.count
        key = (sale.product_name, is_bar)
        prev_count, prev_amount = grouped[key]
        grouped[key] = (prev_count + sale.count, prev_amount + amount)

    rows: list[BarProductRow] = []
    for (product_name, is_bar), (count, sale_amount) in grouped.items():
        bonus = sale_amount * bar_bonus_percent / 100 if is_bar else 0.0
        rows.append(
            BarProductRow(
                product_name=product_name,
                count=count,
                sale_amount=sale_amount,
                bonus_amount=bonus,
                counts_as_bar=is_bar,
            )
        )

    rows.sort(
        key=lambda row: (
            not row.counts_as_bar,
            -row.sale_amount,
            row.product_name.lower(),
        )
    )
    return rows


def build_shift_bar_breakdown_csv(
    *,
    admin_name: str,
    shift_id: int,
    shift_started: str,
    shift_stopped: str,
    rows: list[BarProductRow],
    bar_bonus_percent: float,
    bar_total: float,
    bar_bonus_total: float,
) -> str:
    pct = format_percent(bar_bonus_percent)
    buffer = StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow(["Palace Adms — продажи за смену"])
    writer.writerow(["Админ", admin_name])
    writer.writerow(["Смена", f"#{shift_id}"])
    writer.writerow(["Начало", shift_started])
    writer.writerow(["Конец", shift_stopped])
    writer.writerow(["% с бара", pct])
    writer.writerow([])
    writer.writerow(["Товар", "Кол-во", "Сумма продаж", "% к ЗП", "В ЗП админа"])

    other_total = 0.0
    for row in rows:
        bonus_pct = pct if row.counts_as_bar else "0%"
        if not row.counts_as_bar:
            other_total += row.sale_amount
        writer.writerow([
            row.product_name,
            row.count,
            _csv_money(row.sale_amount),
            bonus_pct,
            _csv_money(row.bonus_amount),
        ])

    writer.writerow([])
    writer.writerow(["Итого бар", "", _csv_money(bar_total), pct, _csv_money(bar_bonus_total)])
    if other_total > 0:
        writer.writerow(["Итого не бар (0% к ЗП)", "", _csv_money(other_total), "0%", _csv_money(0)])
    writer.writerow(["Итого в ЗП", "", "", "", _csv_money(bar_bonus_total)])
    return buffer.getvalue()


def shift_bar_csv_filename(*, admin_name: str, shift_id: int) -> str:
    return f"shift_{shift_id}_{_safe_filename_part(admin_name)}.csv"


def load_shift_bar_rows(
    api: LangameClient,
    shift: WorkingShift,
    bar_bonus_percent: float,
) -> list[BarProductRow]:
    date_from, date_to = shift_date_range(shift)
    if date_from is None or date_to is None:
        return []
    try:
        sales = api.get_product_sales(date_from=date_from, date_to=date_to)
    except Exception:
        return []
    return collect_shift_bar_rows(sales, shift.id, bar_bonus_percent)
