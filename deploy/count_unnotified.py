#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.config import get_settings
from bot.langame_api import LangameClient
from bot.storage import Storage

settings = get_settings()
api = LangameClient(settings)
storage = Storage(settings.database_path)
try:
    unnotified = 0
    for sh in api.get_working_shifts():
        if not sh.date_stop:
            continue
        if storage.get_link_by_user_id(sh.user_id) is None:
            continue
        if not storage.has_shift_notification(sh.id, "closed"):
            unnotified += 1
    print("unnotified_closed", unnotified)
finally:
    api.close()
