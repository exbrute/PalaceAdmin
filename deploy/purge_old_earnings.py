#!/usr/bin/env python3
from __future__ import annotations

from bot.config import get_settings
from bot.langame_api import LangameClient
from bot.ledger import shift_eligible_for_earnings
from bot.storage import Storage


def main() -> None:
    settings = get_settings()
    if settings.earnings_start_date is None:
        raise SystemExit("EARNINGS_START_DATE is not configured")

    storage = Storage(settings.database_path)
    api = LangameClient(settings)

    try:
        old_shift_ids = [
            shift.id
            for shift in api.get_working_shifts()
            if not shift_eligible_for_earnings(shift, settings)
        ]
        extra_bar = storage.purge_bar_credits_for_shifts(old_shift_ids)
        earnings, bar, notif = storage.purge_earnings_before(settings.earnings_start_date)
        print(
            f"Removed earnings={earnings}, bar_credits={bar + extra_bar}, "
            f"notifications={notif}, orphan_bar={extra_bar}"
        )
    finally:
        api.close()


if __name__ == "__main__":
    main()
