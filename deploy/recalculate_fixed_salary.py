#!/usr/bin/env python3
"""Recalculate fixed salary for all stored shifts using hourly club-shift split."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.config import get_settings
from bot.langame_api import LangameClient
from bot.ledger import recalculate_club_shift_group, shift_eligible_for_earnings
from bot.shift_fixed import club_shift_key
from bot.storage import Storage


def main() -> None:
    settings = get_settings()
    storage = Storage(settings.database_path)
    api = LangameClient(settings)

    try:
        all_shifts = api.get_working_shifts()
        keys: set[str] = set()

        for shift in all_shifts:
            if shift.date_stop is None:
                continue
            if not shift_eligible_for_earnings(shift, settings):
                continue
            if storage.get_link_by_user_id(shift.user_id) is None:
                continue
            key = club_shift_key(shift, settings)
            if key:
                keys.add(key)

        for row in storage._conn.execute(
            "SELECT shift_id FROM shift_earnings"
        ).fetchall():
            shift_id = int(row["shift_id"])
            shift = next((item for item in all_shifts if item.id == shift_id), None)
            if shift is None:
                continue
            key = club_shift_key(shift, settings)
            if key:
                keys.add(key)

        recalculated_groups = 0
        updated_shifts = 0
        for club_key in sorted(keys):
            new_ids, error = recalculate_club_shift_group(
                api, storage, settings, all_shifts, club_key
            )
            if error:
                raise SystemExit(error)
            recalculated_groups += 1
            group_size = storage._conn.execute(
                "SELECT COUNT(*) FROM shift_earnings WHERE club_shift_key = ?",
                (club_key,),
            ).fetchone()[0]
            updated_shifts += int(group_size)
            if new_ids:
                print(f"{club_key}: newly synced {new_ids}")

        print(f"club_shift_groups={recalculated_groups}")
        print(f"shift_earnings_rows={updated_shifts}")
    finally:
        api.close()


if __name__ == "__main__":
    main()
