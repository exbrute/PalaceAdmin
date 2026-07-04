#!/usr/bin/env python3
"""Mark historical shifts as notified so managers don't get a backlog of CSV files."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.config import get_settings
from bot.langame_api import LangameClient
from bot.shift_notify import (
    EVENT_SHIFT_CLOSED,
    EVENT_SHIFT_OPENED,
    _shift_is_eligible_for_notification,
)
from bot.storage import Storage


def main() -> None:
    settings = get_settings()
    api = LangameClient(settings)
    storage = Storage(settings.database_path)
    tz = ZoneInfo(settings.settlement_timezone)
    now = datetime.now(tz)
    marked_open = 0
    marked_closed = 0
    try:
        for shift in api.get_working_shifts():
            link = storage.get_link_by_user_id(shift.user_id)
            if link is None:
                continue
            if (
                shift.date_stop is None
                and shift.date_start is not None
                and not storage.has_shift_notification(shift.id, EVENT_SHIFT_OPENED)
                and not _shift_is_eligible_for_notification(
                    shift, EVENT_SHIFT_OPENED, settings=settings, now=now
                )
            ):
                storage.mark_shift_notification(shift.id, EVENT_SHIFT_OPENED)
                marked_open += 1
            if (
                shift.date_stop is not None
                and not storage.has_shift_notification(shift.id, EVENT_SHIFT_CLOSED)
                and not _shift_is_eligible_for_notification(
                    shift, EVENT_SHIFT_CLOSED, settings=settings, now=now
                )
            ):
                storage.mark_shift_notification(shift.id, EVENT_SHIFT_CLOSED)
                marked_closed += 1
        print(f"marked_open={marked_open} marked_closed={marked_closed}")
    finally:
        api.close()


if __name__ == "__main__":
    main()
