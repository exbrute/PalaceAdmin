#!/usr/bin/env python3
from bot.config import get_settings
from bot.langame_api import LangameClient, resolve_shift_nal_beznal, shift_nal_revenue, shift_beznal_revenue
from bot.salary import shift_date_range

api = LangameClient(get_settings())
s = next(x for x in api.get_working_shifts() if x.date_stop is None)
d1, d2 = shift_date_range(s)
raw = [x for x in api._get_paginated("/working_shifts/list") if int(x["id"]) == s.id][0]
print("shift fields", {k: raw.get(k) for k in ["nal", "beznal", "mobile_pay", "yandex_pay"]})
print("official", shift_nal_revenue(s), shift_beznal_revenue(s), "sum", shift_nal_revenue(s) + shift_beznal_revenue(s))
nal, bez = resolve_shift_nal_beznal(api, s, d1, d2)
print("live", nal, bez, "sum", nal + bez)
print("gap vs official", (nal + bez) - (shift_nal_revenue(s) + shift_beznal_revenue(s)))
api.close()
