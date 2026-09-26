from __future__ import annotations

import html
import re
from datetime import date, datetime

from bot.config import Settings
from bot.ledger import AdminBalance, BotPeriodSummary, OpenShiftStats, format_fixed_breakdown
from bot.pay_period import PayPeriod
from bot.services import get_bar_bonus_percent
from bot.storage import FineRecord, ShiftEarning, Storage, UserLink

_TG_EMOJI_RE = re.compile(r'<tg-emoji emoji-id="\d+">(.*?)</tg-emoji>')


def plain(text: str) -> str:
    return html.unescape(_TG_EMOJI_RE.sub(r"\1", text)).strip()


def fmt_date(value: date | None) -> str | None:
    return value.strftime("%d.%m.%Y") if value else None


def fmt_datetime(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return value.strftime("%d.%m.%Y %H:%M")


def money(value: float) -> float:
    return round(float(value), 2)


def balance_to_dict(balance: AdminBalance) -> dict:
    return {
        "balance": money(balance.balance),
        "shifts_count": balance.shifts_count,
        "shift_earned": money(balance.shift_earned),
        "bar_bonus_instant": money(balance.bar_bonus_instant),
        "gross_earned": money(balance.gross_earned),
        "fines_total": money(balance.fines_total),
        "settled_total": money(balance.settled_total),
    }


def earning_to_dict(storage: Storage, settings: Settings, earning: ShiftEarning) -> dict:
    fines = storage.sum_fines(earning.telegram_id, earning.shift_id)
    return {
        "shift_id": earning.shift_id,
        "start": fmt_datetime(earning.shift_start),
        "stop": fmt_datetime(earning.shift_stop),
        "bar_sales": money(earning.bar_sales),
        "sales_count": earning.sales_count,
        "bar_bonus": money(earning.bar_bonus),
        "bar_percent": get_bar_bonus_percent(storage, settings),
        "fixed_total": money(earning.fixed_salary),
        "fixed_text": format_fixed_breakdown(
            settings,
            worked_hours=earning.worked_hours,
            fixed_work=earning.fixed_work,
            fixed_cleaning=earning.fixed_cleaning,
            fixed_total=earning.fixed_salary,
        ),
        "fines": money(fines),
        "net": money(earning.gross_amount - fines),
    }


def open_shift_to_dict(stats: OpenShiftStats) -> dict:
    return {
        "shift_id": stats.shift.id,
        "start": fmt_datetime(stats.shift.date_start),
        "bar_total": money(stats.bar_total),
        "sales_count": stats.sales_count,
        "bar_bonus": money(stats.bar_bonus),
        "bar_percent": stats.bar_percent,
        "fixed_total": money(stats.fixed_share.fixed_total),
        "fixed_text": stats.fixed_text,
        "fines": money(stats.fines),
        "net": money(stats.net),
        "group_size": stats.group_size,
        "nal": None if stats.nal is None else money(stats.nal),
        "beznal": None if stats.beznal is None else money(stats.beznal),
        "total_revenue": None if stats.total_revenue is None else money(stats.total_revenue),
        "bar_share_percent": (
            None if stats.bar_share_percent is None else round(stats.bar_share_percent, 2)
        ),
    }


def period_to_dict(period: PayPeriod) -> dict:
    return {
        "label": period.half_label,
        "date_from": fmt_date(period.date_from),
        "date_to": fmt_date(period.date_to),
        "next_payout": fmt_date(period.next_payout),
    }


def period_summary_to_dict(
    storage: Storage,
    settings: Settings,
    summary: BotPeriodSummary,
) -> dict:
    return {
        "shifts": len(summary.earnings),
        "bar_sales": money(summary.bar_sales_total),
        "bar_bonus": money(summary.bar_bonus_total),
        "bar_percent": get_bar_bonus_percent(storage, settings),
        "fixed": money(summary.fixed_total),
        "gross": money(summary.gross_earned),
        "fines": money(summary.fines_total),
        "net": money(summary.net_amount),
        "earnings": [earning_to_dict(storage, settings, item) for item in summary.earnings],
    }


def fine_to_dict(storage: Storage, fine: FineRecord) -> dict:
    link = storage.get_link(fine.telegram_id)
    return {
        "id": fine.id,
        "telegram_id": fine.telegram_id,
        "admin_name": Storage.admin_name(link, fine.telegram_id),
        "amount": money(fine.amount),
        "reason": fine.reason,
        "shift_id": fine.shift_id,
        "created_at": fmt_datetime(fine.created_at),
    }


def admin_brief(link: UserLink) -> dict:
    return {
        "telegram_id": link.telegram_id,
        "name": Storage.admin_name(link),
        "langame_user_id": link.user_id or None,
        "email": link.email if link.user_id else None,
    }
