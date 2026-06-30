from __future__ import annotations

import csv
from io import StringIO

from bot.config import Settings
from bot.ledger import get_admin_balance, get_period_summary, sync_all_admins
from bot.langame_api import LangameClient
from bot.pay_period import PayPeriod
from bot.salary import format_money
from bot.services import format_percent, get_bar_bonus_percent
from bot.storage import ROLE_ADMIN, Storage


def build_payroll_csv(
    storage: Storage,
    settings: Settings,
    period: PayPeriod,
) -> str:
    bar_percent = format_percent(get_bar_bonus_percent(storage, settings))
    buffer = StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow(["Palace Adms — ведомость"])
    writer.writerow(["Период", f"{period.date_from:%d.%m.%Y} — {period.date_to:%d.%m.%Y}"])
    writer.writerow(["Полмесяц", period.half_label])
    writer.writerow(["Выплата", f"{period.next_payout:%d.%m.%Y}"])
    writer.writerow(["% с бара", bar_percent])
    writer.writerow([])

    writer.writerow([
        "Администратор",
        "Смен",
        "Продажи бара",
        "% с бара",
        "Фикс",
        "Начислено",
        "Штрафы",
        "Итого за период",
        "Баланс в боте",
    ])

    admins = [link for link in storage.list_links(ROLE_ADMIN) if link.user_id]
    rows: list[tuple[str, int, float, float, float, float, float, float, float]] = []
    total_net = 0.0

    for link in admins:
        summary = get_period_summary(
            storage, link.telegram_id, period.date_from, period.date_to
        )
        balance = get_admin_balance(storage, link.telegram_id)
        name = Storage.admin_name(link)
        rows.append((
            name,
            len(summary.earnings),
            summary.bar_sales_total,
            summary.bar_bonus_total,
            summary.fixed_total,
            summary.gross_earned,
            summary.fines_total,
            summary.net_amount,
            balance.balance,
        ))
        total_net += summary.net_amount

    rows.sort(key=lambda item: item[7], reverse=True)
    for row in rows:
        writer.writerow([
            row[0],
            row[1],
            _csv_money(row[2]),
            _csv_money(row[3]),
            _csv_money(row[4]),
            _csv_money(row[5]),
            _csv_money(row[6]),
            _csv_money(row[7]),
            _csv_money(row[8]),
        ])

    writer.writerow([])
    writer.writerow(["Итого за полмесяца", "", "", "", "", "", "", _csv_money(total_net), ""])
    return buffer.getvalue()


def _csv_money(value: float) -> str:
    return format_money(value).replace("\u00a0", " ").replace("₽", "").strip()


async def prepare_payroll_csv(
    api: LangameClient,
    storage: Storage,
    settings: Settings,
    period: PayPeriod,
) -> tuple[str | None, str | None]:
    _, sync_error = sync_all_admins(api, storage, settings)
    if sync_error:
        return None, sync_error

    admins = [link for link in storage.list_links(ROLE_ADMIN) if link.user_id]
    if not admins:
        return None, "Нет админов с привязанным LANGAME"

    return build_payroll_csv(storage, settings, period), None
