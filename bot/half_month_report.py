from __future__ import annotations

from bot.emojis import e
from bot.config import Settings
from bot.langame_api import LangameClient
from bot.ledger import get_admin_balance, get_period_summary, sync_all_admins
from bot.pay_period import PayPeriod, current_pay_period, format_pay_period_header, today_in_timezone
from bot.salary import format_money
from bot.storage import ROLE_ADMIN, Storage


def build_half_month_report(
    storage: Storage,
    settings: Settings,
    period: PayPeriod,
    *,
    test: bool = False,
) -> str:
    admins = [link for link in storage.list_links(ROLE_ADMIN) if link.user_id]
    lines = [
        f"{e('test')} ТЕСТ — итоги полмесяца" if test else f"{e('folder')} Закрытие полмесяца — итоги",
        "",
        format_pay_period_header(period),
        "",
    ]

    if not admins:
        lines.append("Нет админов с привязанным LANGAME.")
        return "\n".join(lines)

    total_net = 0.0
    rows: list[tuple[str, float, int, float]] = []
    for link in admins:
        summary = get_period_summary(
            storage, link.telegram_id, period.date_from, period.date_to
        )
        balance = get_admin_balance(storage, link.telegram_id, settings)
        name = Storage.admin_name(link)
        rows.append((name, summary.net_amount, len(summary.earnings), balance.balance))
        total_net += summary.net_amount

    rows.sort(key=lambda item: item[1], reverse=True)
    for name, net_amount, shift_count, balance in rows:
        lines.append(
            f"• {name}: {format_money(net_amount)} ({shift_count} смен), "
            f"баланс {format_money(balance)}"
        )

    lines.extend(["", f"{e('money')} Итого к выплате: {format_money(total_net)}"])
    if test:
        lines.append(f"\n{e('warning')} Это тестовое уведомление.")
    return "\n".join(lines)


def prepare_half_month_report(
    api: LangameClient,
    storage: Storage,
    settings: Settings,
    period: PayPeriod,
    *,
    test: bool = False,
) -> tuple[str | None, str | None]:
    sync_error = sync_all_admins(api, storage, settings)[1]
    if sync_error:
        return None, sync_error
    return build_half_month_report(storage, settings, period, test=test), None


def build_current_half_month_test_report(
    api: LangameClient,
    storage: Storage,
    settings: Settings,
) -> tuple[str | None, str | None]:
    today = today_in_timezone(settings.settlement_timezone)
    period = current_pay_period(today)
    return prepare_half_month_report(api, storage, settings, period, test=True)
