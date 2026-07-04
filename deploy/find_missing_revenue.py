#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.config import get_settings
from bot.langame_api import (
    LangameClient,
    _transaction_counts_in_revenue_beznal,
    _transaction_is_beznal,
    resolve_shift_nal_beznal,
)
from bot.salary import shift_date_range


def calc_shift(shift, api):
    d1, d2 = shift_date_range(shift)
    raw_tx = [
        x
        for x in api._get_paginated(
            "/transactions/list", {"date_from": str(d1), "date_to": str(d2)}
        )
        if int(x.get("working_shift_id") or 0) == shift.id
        and int(x.get("cancel") or 0) == 0
        and float(x.get("balance") or 0) > 0
    ]
    raw_sales = [
        x
        for x in api._get_paginated(
            "/products/expense", {"date_from": str(d1), "date_to": str(d2)}
        )
        if int(x.get("working_shift_id") or 0) == shift.id
        and int(x.get("cancel") or 0) == 0
    ]

    def tx_bez(x):
        if not float(x.get("Beznal") or 0):
            return False
        a = str(x.get("admin") or "") == "1"
        s = str(x.get("soft") or "") == "1"
        m = float(x.get("mobile") or 0) > 0
        p = float(x.get("payment_1C") or 0) > 0
        if a and s:
            return False
        if a and not s:
            return True
        if s and not a:
            return True
        if m and not a and p:
            return True
        if not a and not s and not m and p:
            return True
        return False

    tx_n = sum(float(x["balance"]) for x in raw_tx if not float(x.get("Beznal") or 0))
    tx_b = sum(float(x["balance"]) for x in raw_tx if tx_bez(x))
    pn = sum(
        float(x.get("price_sale") or 0) * int(x.get("count") or 0)
        for x in raw_sales
        if not int(x.get("beznal") or 0)
    )
    pb = sum(
        float(x.get("price_sale") or 0) * int(x.get("count") or 0)
        for x in raw_sales
        if int(x.get("beznal") or 0)
    )
    return tx_n + pn, tx_b + pb


def main() -> None:
    from bot.salary import shift_date_range

    api = LangameClient(get_settings())
    try:
        for sid in [13, 382]:
            shift = next(s for s in api.get_working_shifts() if s.id == sid)
            n, b = calc_shift(shift, api)
            off_n = shift.cash_nal - shift.refunds_nal
            off_b = (
                shift.cash_beznal
                + shift.mobile_pay
                + shift.yandex_pay
                - shift.refunds_beznal
            )
            print(
                f"shift {sid}: live {n:.0f}/{b:.0f}={n+b:.0f} "
                f"official {off_n:.0f}/{off_b:.0f}={off_n+off_b:.0f} "
                f"diff={(n+b)-(off_n+off_b):+.0f}"
            )
    finally:
        api.close()


if __name__ == "__main__":
    main()

