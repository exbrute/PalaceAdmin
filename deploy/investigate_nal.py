#!/usr/bin/env python3
from __future__ import annotations

import sys
from collections import Counter
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
        open_shifts = [s for s in api.get_working_shifts() if s.date_stop is None]
        if not open_shifts:
            print("no open shift")
            return
        shift = open_shifts[0]
        raw_shift = [
            item
            for item in api._get_paginated("/working_shifts/list")
            if int(item["id"]) == shift.id
        ][0]
        print("=== SHIFT API ===")
        for key in sorted(raw_shift.keys()):
            print(f"  {key}: {raw_shift[key]}")
        print("parsed:", shift.cash_nal, shift.cash_beznal, shift.mobile_pay, shift.yandex_pay)

        date_from, date_to = shift_date_range(shift)
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
        print("\n=== TX FIELD COMBOS ===")
        combos = Counter(
            (
                item.get("Beznal"),
                item.get("mobile"),
                item.get("payment_1C"),
                item.get("admin"),
                item.get("soft"),
            )
            for item in raw_tx
        )
        for combo, count in combos.most_common():
            subset = [
                item
                for item in raw_tx
                if (
                    item.get("Beznal"),
                    item.get("mobile"),
                    item.get("payment_1C"),
                    item.get("admin"),
                    item.get("soft"),
                )
                == combo
            ]
            total = sum(float(item.get("balance") or 0) for item in subset)
            print(f"  Beznal,mobile,p1c,admin,soft={combo} count={count} sum={total:.2f}")

        print("\n=== CLASSIFICATION TESTS ===")
        tests = {
            "Beznal==0 only": lambda i: not float(i.get("Beznal") or 0),
            "Beznal==1 only": lambda i: float(i.get("Beznal") or 0) > 0,
            "Beznal only (no p1c/mobile)": lambda i: float(i.get("Beznal") or 0) > 0
            and not float(i.get("mobile") or 0)
            and not float(i.get("payment_1C") or 0),
            "payment_1C==0 is nal": lambda i: not float(i.get("payment_1C") or 0),
            "payment_1C==1 is beznal": lambda i: float(i.get("payment_1C") or 0) > 0,
        }
        for name, pred in tests.items():
            nal = sum(
                float(i.get("balance") or 0) for i in raw_tx if pred(i) and not float(i.get("Beznal") or 0)
            )
            bez = sum(
                float(i.get("balance") or 0) for i in raw_tx if pred(i) and float(i.get("Beznal") or 0)
            )
            # simpler split by pred for nal side vs not
            yes = sum(float(i.get("balance") or 0) for i in raw_tx if pred(i))
            no = sum(float(i.get("balance") or 0) for i in raw_tx if not pred(i))
            print(f"  {name}: match={yes:.2f} other={no:.2f}")

        print("\n=== NAL by Beznal==0 ===")
        nal_tx = [i for i in raw_tx if not float(i.get("Beznal") or 0)]
        print(f"count={len(nal_tx)} sum={sum(float(i['balance']) for i in nal_tx):.2f}")
        for item in nal_tx[:10]:
            print(
                f"  #{item['id']} bal={item['balance']} Beznal={item.get('Beznal')} "
                f"p1c={item.get('payment_1C')} mobile={item.get('mobile')}"
            )

        # probe endpoints
        print("\n=== OTHER ENDPOINTS ===")
        for path in [
            "/working_shifts/view",
            f"/working_shifts/{shift.id}",
            "/reports/revenue",
            "/reports/shift_revenue",
        ]:
            try:
                response = api._client.get(path, params={"id": shift.id})
                print(path, response.status_code, response.text[:120].replace("\n", " "))
            except Exception as exc:
                print(path, exc)
    finally:
        api.close()


if __name__ == "__main__":
    main()
