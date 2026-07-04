#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.config import get_settings
from bot.langame_api import LangameClient, sale_counts_as_bar, resolve_shift_nal_beznal
from bot.salary import shift_date_range


def is_beznal(item: dict) -> bool:
    return (
        float(item.get("Beznal") or 0) > 0
        or float(item.get("mobile") or 0) > 0
        or float(item.get("payment_1C") or 0) > 0
    )


def main() -> None:
    settings = get_settings()
    api = LangameClient(settings)
    try:
        open_shifts = [s for s in api.get_working_shifts() if s.date_stop is None]
        if not open_shifts:
            print("NO_OPEN_SHIFT")
            return
        shift = open_shifts[0]
        date_from, date_to = shift_date_range(shift)
        nal, beznal = resolve_shift_nal_beznal(
            api, shift, date_from, date_to
        )
        total = nal + beznal
        print(f"SHIFT {shift.id} start={shift.date_start}")
        print(f"NAL {nal:.2f}")
        print(f"BEZNAL {beznal:.2f}")
        print(f"TOTAL {total:.2f}")

        raw_tx = [
            item
            for item in api._get_paginated(
                "/transactions/list",
                {"date_from": str(date_from), "date_to": str(date_to)},
            )
            if int(item.get("working_shift_id") or 0) == shift.id
            and int(item.get("cancel") or 0) == 0
            and float(item.get("balance") or 0) > 0
        ]
        print(f"TX_COUNT {len(raw_tx)}")
        print("--- TX NAL ---")
        for item in sorted(raw_tx, key=lambda row: str(row.get("date_update") or "")):
            if is_beznal(item):
                continue
            print(f"  #{item['id']} {item.get('date_update')} {float(item['balance']):.2f}")
        print("--- TX BEZNAL ---")
        for item in sorted(raw_tx, key=lambda row: str(row.get("date_update") or "")):
            if not is_beznal(item):
                continue
            print(f"  #{item['id']} {item.get('date_update')} {float(item['balance']):.2f}")

        sales = api.get_product_sales(date_from, date_to)
        shift_sales = [
            sale
            for sale in sales
            if sale.working_shift_id == shift.id and sale.cancel == 0
        ]
        print("--- PRODUCTS ---")
        bar_sum = 0.0
        other_sum = 0.0
        for sale in sorted(shift_sales, key=lambda row: row.date):
            amount = sale.price_sale * sale.count
            kind = "bar" if sale_counts_as_bar(sale) else "other"
            if kind == "bar":
                bar_sum += amount
            else:
                other_sum += amount
            print(
                f"  #{sale.id} {kind} {sale.product_name!r} "
                f"x{sale.count} @ {sale.price_sale:.2f} = {amount:.2f}"
            )
        print(
            f"PRODUCTS_BAR {bar_sum:.2f} "
            f"PRODUCTS_OTHER {other_sum:.2f} "
            f"PRODUCTS_TOTAL {bar_sum + other_sum:.2f}"
        )
    finally:
        api.close()


if __name__ == "__main__":
    main()
