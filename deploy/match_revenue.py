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


def main() -> None:
    settings = get_settings()
    api = LangameClient(settings)
    try:
        shift = next(s for s in api.get_working_shifts() if s.date_stop is None)
        d1, d2 = shift_date_range(shift)
        raw_sales = [
            x
            for x in api._get_paginated(
                "/products/expense", {"date_from": str(d1), "date_to": str(d2)}
            )
            if int(x.get("working_shift_id") or 0) == shift.id
            and int(x.get("cancel") or 0) == 0
        ]
        print("PRODUCT KEYS", sorted(raw_sales[0].keys()) if raw_sales else [])
        for item in raw_sales[:3]:
            print("sample", {k: item.get(k) for k in sorted(item.keys())})

        combos: dict[tuple, float] = {}
        for item in raw_sales:
            key = (
                item.get("Beznal"),
                item.get("nal"),
                item.get("beznal"),
                item.get("mobile"),
                item.get("payment"),
            )
            amt = float(item.get("price_sale") or 0) * int(item.get("count") or 0)
            combos[key] = combos.get(key, 0) + amt
        print("PRODUCT PAYMENT COMBOS")
        for key, amt in sorted(combos.items(), key=lambda x: -x[1]):
            print(f"  {key} = {amt:.2f}")

        raw_tx = [
            x
            for x in api._get_paginated(
                "/transactions/list", {"date_from": str(d1), "date_to": str(d2)}
            )
            if int(x.get("working_shift_id") or 0) == shift.id
            and int(x.get("cancel") or 0) == 0
            and float(x.get("balance") or 0) > 0
        ]
        # target user: nal 1790 beznal 5791 total 7781
        target_nal, target_bez, target_total = 1790, 5791, 7781
        print(f"TARGET nal={target_nal} beznal={target_bez} total={target_total}")

        tx_nal = sum(float(x["balance"]) for x in raw_tx if not float(x.get("Beznal") or 0))
        tx_bez = sum(float(x["balance"]) for x in raw_tx if float(x.get("Beznal") or 0))
        prod_all = sum(float(x.get("price_sale") or 0) * int(x.get("count") or 0) for x in raw_sales)
        print(f"TX nal={tx_nal} beznal={tx_bez} sum={tx_nal+tx_bez} products={prod_all}")

        # try product Beznal field if exists
        for field in ["Beznal", "beznal", "nal", "payment_type"]:
            if raw_sales and field in raw_sales[0]:
                pn = sum(
                    float(x.get("price_sale") or 0) * int(x.get("count") or 0)
                    for x in raw_sales
                    if not float(x.get(field) or 0)
                )
                pb = sum(
                    float(x.get("price_sale") or 0) * int(x.get("count") or 0)
                    for x in raw_sales
                    if float(x.get(field) or 0)
                )
                print(f"products by {field}: nal={pn} beznal={pb} total={pn+pb}")

        print("TRY nal=tx_nal+prod_nal")
        # common patterns
        candidates = [
            ("tx only", tx_nal, tx_bez),
            ("tx+all prod to nal", tx_nal + prod_all, tx_bez),
            ("tx+all prod to beznal", tx_nal, tx_bez + prod_all),
            ("tx bez - prod", tx_nal, tx_bez - prod_all),
            ("tx nal + prod, bez - prod", tx_nal + prod_all, max(0, tx_bez - prod_all)),
        ]
        for name, n, b in candidates:
            print(f"  {name}: nal={n:.0f} beznal={b:.0f} total={n+b:.0f} diff={abs(n+b-target_total):.0f}")
    finally:
        api.close()


if __name__ == "__main__":
    main()
