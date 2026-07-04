#!/usr/bin/env python3
"""Remove bar credits and recalculate shifts for non-bar (закупка) sales."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.config import get_settings
from bot.langame_api import LangameClient, sale_counts_as_bar
from bot.ledger import recalculate_club_shift_group, shift_eligible_for_earnings
from bot.shift_fixed import club_shift_key
from bot.storage import Storage


def main() -> None:
    settings = get_settings()
    storage = Storage(settings.database_path)
    api = LangameClient(settings)

    try:
        date_from = settings.earnings_start_date
        date_to = datetime.now().date()
        if date_from is None:
            raise SystemExit("EARNINGS_START_DATE is not configured")

        sales = api.get_product_sales(date_from=date_from, date_to=date_to)
        non_bar_sales = [sale for sale in sales if not sale_counts_as_bar(sale)]
        non_bar_ids = {sale.id for sale in non_bar_sales}

        removed_credits = 0
        removed_bonus = 0.0
        for sale_id in list(non_bar_ids):
            row = storage._conn.execute(
                "SELECT sale_id, bonus_amount FROM bar_sale_credits WHERE sale_id = ?",
                (sale_id,),
            ).fetchone()
            if row is None:
                continue
            storage._conn.execute(
                "DELETE FROM bar_sale_credits WHERE sale_id = ?",
                (sale_id,),
            )
            removed_credits += 1
            removed_bonus += float(row["bonus_amount"])

        shifts = {
            shift.id: shift
            for shift in api.get_working_shifts()
            if shift_eligible_for_earnings(shift, settings)
        }
        keys: set[str] = set()
        for row in storage._conn.execute("SELECT shift_id FROM shift_earnings").fetchall():
            shift = shifts.get(int(row["shift_id"]))
            if shift is None:
                continue
            key = club_shift_key(shift, settings)
            if key:
                keys.add(key)

        recalculated = 0
        for club_key in sorted(keys):
            _, error = recalculate_club_shift_group(
                api, storage, settings, list(shifts.values()), club_key
            )
            if error:
                raise SystemExit(error)
            recalculated += storage._conn.execute(
                "SELECT COUNT(*) FROM shift_earnings WHERE club_shift_key = ?",
                (club_key,),
            ).fetchone()[0]

        print(f"non_bar_sales={len(non_bar_sales)}")
        print(f"removed_credits={removed_credits} removed_bonus={removed_bonus:.2f}")
        print(f"recalculated_shifts={recalculated}")
        for sale in non_bar_sales[:20]:
            amount = sale.price_sale * sale.count
            print(
                f"  sale #{sale.id} shift #{sale.working_shift_id}: "
                f"{sale.product_name!r} x{sale.count} = {amount:.2f}"
            )
        if len(non_bar_sales) > 20:
            print(f"  ... and {len(non_bar_sales) - 20} more")
    finally:
        api.close()


if __name__ == "__main__":
    main()
