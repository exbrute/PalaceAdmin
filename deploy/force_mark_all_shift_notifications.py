#!/usr/bin/env python3
"""Force-mark ALL linked closed/open shifts as notified — stops CSV spam immediately."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.config import get_settings
from bot.langame_api import LangameClient
from bot.shift_notify import EVENT_SHIFT_CLOSED, EVENT_SHIFT_OPENED
from bot.storage import Storage


def main() -> None:
    settings = get_settings()
    api = LangameClient(settings)
    storage = Storage(settings.database_path)
    marked_open = 0
    marked_closed = 0
    try:
        for shift in api.get_working_shifts():
            if storage.get_link_by_user_id(shift.user_id) is None:
                continue
            if shift.date_stop is None and shift.date_start is not None:
                if not storage.has_shift_notification(shift.id, EVENT_SHIFT_OPENED):
                    storage.mark_shift_notification(shift.id, EVENT_SHIFT_OPENED)
                    marked_open += 1
            if shift.date_stop is not None:
                if not storage.has_shift_notification(shift.id, EVENT_SHIFT_CLOSED):
                    storage.mark_shift_notification(shift.id, EVENT_SHIFT_CLOSED)
                    marked_closed += 1
        print(f"force_marked open={marked_open} closed={marked_closed}")
    finally:
        api.close()


if __name__ == "__main__":
    main()
