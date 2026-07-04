#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.config import get_settings
from bot.langame_api import LangameClient
from bot.salary import shift_date_range


def tx_is_yandex_beznal(item: dict) -> bool:
    beznal = float(item.get("Beznal") or 0) > 0
    admin = str(item.get("admin") or "") == "1"
    soft = str(item.get("soft") or "") == "1"
    mobile = float(item.get("mobile") or 0) > 0
    p1c = float(item.get("payment_1C") or 0) > 0

    if beznal and admin and not soft:
        return True
    if beznal and soft and not admin and p1c:
        return True
    if beznal and mobile and not admin and p1c:
        return True
    return False


def tx_is_nal(item: dict) -> bool:
    return float(item.get("Beznal") or 0) == 0


def classify_shift(api: LangameClient, shift_id: int | None = None) -> None:
    shifts = api.get_working_shifts()
    if shift_id is None:
        shift = next(s for s in shifts if s.date_stop is None)
    else:
        shift = next(s for s in shifts if s.id == shift_id)

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

    tx_nal = sum(float(x["balance"]) for x in raw_tx if tx_is_nal(x))
    tx_bez = sum(float(x["balance"]) for x in raw_tx if tx_is_yandex_beznal(x))
    prod_nal = sum(
        float(x.get("price_sale") or 0) * int(x.get("count") or 0)
        for x in raw_sales
        if not int(x.get("beznal") or 0)
    )
    prod_bez = sum(
        float(x.get("price_sale") or 0) * int(x.get("count") or 0)
        for x in raw_sales
        if int(x.get("beznal") or 0)
        and not int(x.get("from_magazine") or 0)
        and int(x.get("payment_1C") or 0)
    )

    official_nal = shift.cash_nal - shift.refunds_nal
    official_bez = (
        shift.cash_beznal + shift.mobile_pay + shift.yandex_pay - shift.refunds_beznal
    )
    print(f"shift #{shift.id} closed={shift.date_stop is not None}")
    print(
        f"  official nal={official_nal:.2f} bez={official_bez:.2f} "
        f"(yandex={shift.yandex_pay:.2f} mobile={shift.mobile_pay:.2f})"
    )
    print(
        f"  live     nal={tx_nal + prod_nal:.2f} bez={tx_bez + prod_bez:.2f} "
        f"total={tx_nal + prod_nal + tx_bez + prod_bez:.2f}"
    )
    print(
        f"  diff     nal={tx_nal + prod_nal - official_nal:+.2f} "
        f"bez={tx_bez + prod_bez - official_bez:+.2f}"
    )


def main() -> None:
    api = LangameClient(get_settings())
    try:
        classify_shift(api, 13)
        classify_shift(api)
    finally:
        api.close()


if __name__ == "__main__":
    main()
