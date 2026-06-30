from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.bar_sales import notify_admin_shift_closed
from bot.messaging import reply as reply_message, send as send_message
from bot.emojis import e
from bot.half_month_report import build_current_half_month_test_report
from bot.keyboards import build_main_keyboard
from bot.langame_api import LangameApiError, LangameClient
from bot.roles import has_manager_access, is_developer, require_manager, role_label
from bot.ledger import (
    format_earning_line,
    format_period_summary,
    get_admin_balance,
    get_period_summary,
    sync_admin_shifts,
    sync_all_admins,
    sync_shift_by_id,
)
from bot.payroll_export import prepare_payroll_csv
from bot.pay_period import current_pay_period, today_in_timezone
from bot.salary import format_money
from bot.services import find_shift, format_percent, get_bar_bonus_percent, set_bar_bonus_percent
from bot.shift_notify import notify_managers
from bot.storage import ROLE_ADMIN, Storage, UserLink
from bot.texts import (
    admin_not_found,
    admin_removed,
    admin_removed_notify,
    cannot_remove_developer,
    cannot_remove_manager,
    fine_already_cancelled,
    fine_cancelled,
    fine_cancelled_notify,
    fine_issued,
    fine_not_found,
    fine_received,
    no_fines,
    remove_admin_failed,
)


MANAGER_HELP = (
    f"{e('folder')} Команды управляющего:\n"
    f"/team — {e('people')} команда в боте\n"
    f"/admin <имя|telegram_id> — {e('folder')} карточка администратора\n"
    f"/shiftreport <id> — {e('gear')} отчёт по смене (LANGAME)\n"
    f"/fine <имя|telegram_id> <сумма> <причина> — {e('warning')} штраф\n"
    f"/fines [имя|telegram_id] — {e('newspaper')} список штрафов\n"
    f"/cancel_fine <id> — {e('check')} отменить штраф\n"
    f"/remove_admin <имя|telegram_id> — {e('prohibited')} убрать админа из бота\n"
    f"/payroll — {e('money_bag')} ведомость за полмесяца\n"
    f"/leaderboard — {e('chart_up')} рейтинг продаж бара за полмесяца\n"
    f"/bar_percent [число] — {e('burger')} процент с бара\n"
    f"/broadcast <текст> — {e('megaphone')} сообщение всем админам\n"
    f"/promote <telegram_id> — {e('person')} назначить управляющим\n"
    f"/demote <telegram_id> — {e('label')} снять роль управляющего"
)


def _resolve_target_admin(storage: Storage, query: str) -> UserLink | None:
    return storage.resolve_bot_admin(query)


async def _reply_manager(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    settings = context.application.bot_data["settings"]
    storage: Storage = context.application.bot_data["storage"]
    keyboard = build_main_keyboard(update.effective_user.id, settings, storage)
    await reply_message(update.message, text, reply_markup=keyboard)


async def team(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_manager(update, context):
        return

    settings = context.application.bot_data["settings"]
    storage: Storage = context.application.bot_data["storage"]
    links = storage.list_links(ROLE_ADMIN)

    lines = [f"{e('people')} Команда в боте:", "", f"{e('person')} Управляющие:"]
    seen_managers: set[int] = set()

    for telegram_id in sorted(settings.manager_telegram_ids):
        seen_managers.add(telegram_id)
        link = storage.get_link(telegram_id)
        name = Storage.admin_name(link, telegram_id)
        lines.append(f"• {name} — TG: {telegram_id}")

    for member in storage.list_staff_managers():
        if member.telegram_id in seen_managers:
            continue
        seen_managers.add(member.telegram_id)
        name = member.username or "—"
        lines.append(f"• {name} — TG: {member.telegram_id}")

    if not seen_managers:
        lines.append("• пока нет")

    if settings.developer_telegram_ids:
        lines.extend(["", f"{e('tools')} Разработчики:"])
        for telegram_id in sorted(settings.developer_telegram_ids):
            lines.append(f"• TG: {telegram_id}")

    lines.extend(["", f"{e('person')} Администраторы:"])
    if not links:
        lines.append("• пока нет")
    else:
        for link in links:
            name = Storage.admin_name(link)
            balance = get_admin_balance(storage, link.telegram_id)
            langame = f"LANGAME id: {link.user_id}" if link.user_id else "LANGAME не привязан"
            lines.append(
                f"• {name}\n  {langame}, TG: {link.telegram_id}\n"
                f"  {e('money_bag')} Баланс: {format_money(balance.balance)}"
            )

    await reply_message(update.message, "\n".join(lines))


async def admin_card(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query: str | None = None,
) -> None:
    if not await require_manager(update, context):
        return

    if query is None:
        if not context.args:
            await reply_message(update.message,"Введите имя или Telegram ID администратора")
            return
        query = context.args[0]

    settings = context.application.bot_data["settings"]
    api: LangameClient = context.application.bot_data["api"]
    storage: Storage = context.application.bot_data["storage"]

    link = _resolve_target_admin(storage, query)
    if not link:
        await reply_message(update.message,"Администратор не найден в боте")
        return

    name = Storage.admin_name(link)
    balance = get_admin_balance(storage, link.telegram_id)
    today = today_in_timezone(settings.settlement_timezone)
    period = current_pay_period(today)

    if link.user_id:
        _, sync_error = sync_admin_shifts(api, storage, settings, link)
        if sync_error:
            await reply_message(update.message,sync_error)
            return

    month_summary = get_period_summary(
        storage, link.telegram_id, period.date_from, period.date_to
    )
    fines = storage.list_fines(link.telegram_id, limit=5)
    last_earnings = storage.list_shift_earnings(link.telegram_id, limit=1)

    lines = [
        f"{e('folder')} Карточка: {name}",
        f"{e('info')} Telegram ID: {link.telegram_id}",
        f"{e('person')} Роль: {role_label(link.role)}",
        f"{e('money_bag')} Баланс в боте: {format_money(balance.balance)}",
    ]

    if link.user_id:
        lines.extend([
            f"LANGAME id: {link.user_id}",
            f"Email: {link.email}",
            "",
            f"За {period.half_label}:",
            f"Смен: {len(month_summary.earnings)}",
            f"Продажи бара: {format_money(month_summary.bar_sales_total)}",
            f"Начислено: {format_money(month_summary.gross_earned)}",
            f"Штрафы: −{format_money(month_summary.fines_total)}",
            f"Итого за полмесяца: {format_money(month_summary.net_amount)}",
        ])
        if last_earnings:
            lines.extend(["", f"{e('gear')} Последняя смена:", format_earning_line(storage, last_earnings[0], settings)])
    else:
        lines.extend([
            "",
            "LANGAME не привязан — новые смены не синхронизируются.",
        ])

    if fines:
        lines.append("")
        lines.append("Последние штрафы:")
        for fine in fines:
            shift_part = f", смена #{fine.shift_id}" if fine.shift_id else ""
            lines.append(f"• #{fine.id} −{format_money(fine.amount)}{shift_part}: {fine.reason}")

    await reply_message(update.message, "\n".join(lines))


async def shiftreport(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    shift_id: int | None = None,
) -> None:
    if not await require_manager(update, context):
        return

    if shift_id is None:
        if not context.args or not context.args[0].isdigit():
            await reply_message(update.message,"Введите id смены")
            return
        shift_id = int(context.args[0])

    settings = context.application.bot_data["settings"]
    api: LangameClient = context.application.bot_data["api"]
    storage: Storage = context.application.bot_data["storage"]

    try:
        shift = find_shift(api, shift_id)
    except LangameApiError as exc:
        await reply_message(update.message,str(exc))
        return

    if not shift:
        await reply_message(update.message,f"Смена #{shift_id} не найдена в LANGAME")
        return

    link = storage.get_link_by_user_id(shift.user_id)
    if not link:
        await reply_message(update.message,
            f"Смена #{shift_id} — администратор не зарегистрирован в боте"
        )
        return

    earning, error, fixed = sync_shift_by_id(api, storage, settings, link, shift_id)
    if error:
        await reply_message(update.message,error)
        return
    if earning is None:
        await reply_message(update.message, f"{e('cancel')} Смена #{shift_id} не найдена")
        return
    if fixed is not None:
        await notify_admin_shift_closed(context, storage, link.telegram_id, shift_id)

    name = Storage.admin_name(link)
    await reply_message(
        update.message,
        f"{e('person')} Администратор: {name}\n\n"
        + format_earning_line(storage, earning, settings),
    )


async def _issue_fine(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    args: list[str],
) -> None:
    if len(args) < 3:
        await reply_message(update.message,
            "Использование:\n"
            "/fine <имя|telegram_id> <сумма> <причина>\n"
            "/fine <имя|telegram_id> <сумма> shift:<id> <причина>"
        )
        return

    storage: Storage = context.application.bot_data["storage"]
    link = _resolve_target_admin(storage, args[0])
    if not link:
        await reply_message(update.message,"Администратор не найден в боте")
        return

    amount_raw = args[1].replace(",", ".")
    if not amount_raw.replace(".", "", 1).isdigit():
        await reply_message(update.message,"Сумма должна быть числом")
        return

    amount = float(amount_raw)
    shift_id = None
    reason_parts = args[2:]
    if reason_parts[0].lower().startswith("shift:"):
        shift_part = reason_parts[0].split(":", 1)[1]
        if not shift_part.isdigit():
            await reply_message(update.message,"Укажите id смены: shift:12345")
            return
        shift_id = int(shift_part)
        reason_parts = reason_parts[1:]

    reason = " ".join(reason_parts).strip()
    if not reason:
        await reply_message(update.message,"Укажите причину")
        return

    name = Storage.admin_name(link)
    record_id = storage.add_fine(
        telegram_id=link.telegram_id,
        amount=amount,
        reason=reason,
        created_by=update.effective_user.id,
        shift_id=shift_id,
    )

    await reply_message(update.message,
        fine_issued(record_id, name, amount, reason, shift_id=shift_id)
    )

    try:
        await send_message(context, link.telegram_id, fine_received(record_id, amount, reason, shift_id=shift_id))
    except Exception:
        pass


async def fine(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_manager(update, context):
        return
    await _issue_fine(update, context, args=context.args)


async def fines_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_manager(update, context):
        return

    storage: Storage = context.application.bot_data["storage"]
    telegram_id = None
    name = "все"

    if context.args:
        link = _resolve_target_admin(storage, context.args[0])
        if not link:
            await reply_message(update.message,"Администратор не найден в боте")
            return
        telegram_id = link.telegram_id
        name = Storage.admin_name(link)

    records = storage.list_fines(telegram_id, limit=20)
    if not records:
        await reply_message(update.message,no_fines())
        return

    lines = [f"{e('warning')} Штрафы ({name}):"]
    for record in records:
        admin_link = storage.get_link(record.telegram_id)
        admin_name = Storage.admin_name(admin_link, record.telegram_id)
        shift_part = f", смена #{record.shift_id}" if record.shift_id else ""
        lines.append(
            f"#{record.id}: {admin_name}, −{format_money(record.amount)}{shift_part}\n"
            f"{record.reason}"
        )
    await reply_message(update.message,"\n\n".join(lines))


async def cancel_fine(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_manager(update, context):
        return

    if not context.args or not context.args[0].isdigit():
        await reply_message(update.message,"Использование: /cancel_fine <id>")
        return

    storage: Storage = context.application.bot_data["storage"]
    fine_id = int(context.args[0])
    fine = storage.get_fine(fine_id)
    if fine is None:
        await _reply_manager(update, context, fine_not_found())
        return

    if not storage.cancel_fine(fine_id):
        await _reply_manager(update, context, fine_already_cancelled())
        return

    link = storage.get_link(fine.telegram_id)
    name = Storage.admin_name(link, fine.telegram_id)
    await _reply_manager(
        update,
        context,
        fine_cancelled(fine_id, name, fine.amount, fine.reason),
    )

    try:
        await send_message(context, fine.telegram_id, fine_cancelled_notify(fine_id, fine.amount, fine.reason))
    except Exception:
        pass


async def remove_admin(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query: str | None = None,
) -> None:
    if not await require_manager(update, context):
        return

    if query is None:
        if not context.args:
            await reply_message(update.message,"Введите имя или Telegram ID администратора")
            return
        query = context.args[0]

    settings = context.application.bot_data["settings"]
    storage: Storage = context.application.bot_data["storage"]

    link = _resolve_target_admin(storage, query)
    if not link:
        await _reply_manager(update, context, admin_not_found())
        return

    telegram_id = link.telegram_id
    if is_developer(settings, telegram_id):
        await _reply_manager(update, context, cannot_remove_developer())
        return
    if has_manager_access(settings, storage, telegram_id):
        await _reply_manager(update, context, cannot_remove_manager())
        return

    name = Storage.admin_name(link)
    if not storage.remove_admin(telegram_id):
        await _reply_manager(update, context, remove_admin_failed())
        return

    await _reply_manager(update, context, admin_removed(name, telegram_id))

    try:
        await send_message(context, telegram_id, admin_removed_notify())
    except Exception:
        pass


async def payroll(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_manager(update, context):
        return

    settings = context.application.bot_data["settings"]
    api: LangameClient = context.application.bot_data["api"]
    storage: Storage = context.application.bot_data["storage"]
    today = today_in_timezone(settings.settlement_timezone)
    period = current_pay_period(today)

    _, sync_error = sync_all_admins(api, storage, settings)
    if sync_error:
        await reply_message(update.message,sync_error)
        return

    admins = [link for link in storage.list_links(ROLE_ADMIN) if link.user_id]
    if not admins:
        await reply_message(update.message,"Нет админов с привязанным LANGAME")
        return

    lines = [
        f"{e('money_bag')} Ведомость за {period.half_label} (баланс в боте)",
        f"{e('date')} Период: {period.date_from.strftime('%d.%m.%Y')} — {period.date_to.strftime('%d.%m.%Y')}",
        f"{e('money')} Выплата: {period.next_payout.strftime('%d.%m.%Y')}",
        "",
    ]

    total_net = 0.0
    rows: list[tuple[str, float, int, float]] = []

    for link in admins:
        summary = get_period_summary(
            storage, link.telegram_id, period.date_from, period.date_to
        )
        balance = get_admin_balance(storage, link.telegram_id)
        name = Storage.admin_name(link)
        rows.append((name, summary.net_amount, len(summary.earnings), balance.balance))
        total_net += summary.net_amount

    rows.sort(key=lambda item: item[1], reverse=True)
    for name, net_amount, shift_count, balance in rows:
        lines.append(
            f"• {name}: {format_money(net_amount)} ({shift_count} смен), "
            f"баланс {format_money(balance)}"
        )

    lines.extend(["", f"{e('money')} Итого за полмесяца: {format_money(total_net)}"])
    await reply_message(update.message, "\n".join(lines))


async def payroll_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_manager(update, context):
        return

    settings = context.application.bot_data["settings"]
    api: LangameClient = context.application.bot_data["api"]
    storage: Storage = context.application.bot_data["storage"]
    today = today_in_timezone(settings.settlement_timezone)
    period = current_pay_period(today)

    csv_content, error = await prepare_payroll_csv(api, storage, settings, period)
    if error or csv_content is None:
        await reply_message(update.message, error or "Не удалось сформировать ведомость")
        return

    from io import BytesIO

    from telegram.constants import ParseMode

    filename = f"vedomost_{period.cycle_key}.csv"
    buffer = BytesIO(csv_content.encode("utf-8-sig"))
    buffer.name = filename
    caption = (
        f"{e('chart')} Ведомость за {period.half_label}\n"
        f"{e('date')} {period.date_from.strftime('%d.%m.%Y')} — "
        f"{period.date_to.strftime('%d.%m.%Y')}"
    )
    keyboard = build_main_keyboard(update.effective_user.id, settings, storage)
    await update.message.reply_document(
        document=buffer,
        filename=filename,
        caption=caption,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_manager(update, context):
        return

    settings = context.application.bot_data["settings"]
    api: LangameClient = context.application.bot_data["api"]
    storage: Storage = context.application.bot_data["storage"]
    today = today_in_timezone(settings.settlement_timezone)
    period = current_pay_period(today)

    _, sync_error = sync_all_admins(api, storage, settings)
    if sync_error:
        await reply_message(update.message,sync_error)
        return

    stats: list[tuple[str, float]] = []
    for link in storage.list_links(ROLE_ADMIN):
        if link.user_id == 0:
            continue
        earnings = storage.list_shift_earnings(
            link.telegram_id, period.date_from, period.date_to
        )
        total = sum(item.bar_sales for item in earnings)
        if total > 0:
            stats.append((Storage.admin_name(link), total))

    if not stats:
        await reply_message(update.message,"За полмесяца продаж бара пока нет")
        return

    lines = [f"{e('chart_up')} Рейтинг продаж бара — {period.half_label}", ""]
    for index, (name, total) in enumerate(
        sorted(stats, key=lambda item: item[1], reverse=True),
        start=1,
    ):
        prefix = f"{e('check')}" if index == 1 else f"{e('money')}" if index == 2 else f"{e('chart')}" if index == 3 else f"{index}."
        lines.append(f"{prefix} {name} — {format_money(total)}")

    await reply_message(update.message, "\n".join(lines))


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_manager(update, context):
        return

    if not context.args:
        await reply_message(update.message,"Использование: /broadcast <текст сообщения>")
        return

    text = " ".join(context.args).strip()
    storage: Storage = context.application.bot_data["storage"]
    admins = storage.list_links(ROLE_ADMIN)

    if not admins:
        await reply_message(update.message,"Нет зарегистрированных администраторов")
        return

    sent = 0
    for link in admins:
        try:
            await send_message(context, link.telegram_id, f"Сообщение от управляющего:\n\n{text}")
            sent += 1
        except Exception:
            pass

    await reply_message(update.message,f"Отправлено {sent} из {len(admins)} администраторов")


async def promote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from bot.roles import require_developer

    if not await require_developer(update, context):
        return

    if not context.args or not context.args[0].isdigit():
        await reply_message(update.message,"Использование: /promote <telegram_id> [имя]")
        return

    settings = context.application.bot_data["settings"]
    storage: Storage = context.application.bot_data["storage"]
    telegram_id = int(context.args[0])
    name = context.args[1] if len(context.args) > 1 else f"Управляющий {telegram_id}"

    if is_developer(settings, telegram_id):
        await reply_message(update.message,"Этот пользователь уже разработчик.")
        return
    if has_manager_access(settings, storage, telegram_id):
        await reply_message(update.message,"Этот пользователь уже управляющий.")
        return

    storage.register_staff_manager(telegram_id=telegram_id, username=name)
    await reply_message(update.message,f"Управляющий добавлен: {name} (TG: {telegram_id})")


async def demote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_manager(update, context):
        return

    if not context.args or not context.args[0].isdigit():
        await reply_message(update.message,"Использование: /demote <telegram_id>")
        return

    storage: Storage = context.application.bot_data["storage"]
    telegram_id = int(context.args[0])
    if storage.remove_staff_manager(telegram_id):
        await reply_message(update.message,f"Управляющий {telegram_id} снят")
    else:
        await reply_message(update.message,"Управляющий не найден в боте")


async def set_bar_percent(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    value: float | None = None,
) -> None:
    if not await require_manager(update, context):
        return

    settings = context.application.bot_data["settings"]
    storage: Storage = context.application.bot_data["storage"]

    if value is None:
        current = get_bar_bonus_percent(storage, settings)
        await _reply_manager(
            update,
            context,
            f"{e('burger')} Процент с бара: {format_percent(current)}%\n\n"
            "Новые продажи начисляются по этому проценту.\n"
            "Уже начисленные суммы не пересчитываются.",
        )
        return

    try:
        set_bar_bonus_percent(storage, value)
    except ValueError as exc:
        await _reply_manager(update, context, str(exc))
        return

    await _reply_manager(
        update,
        context,
        f"{e('check')} Процент с бара изменён: {format_percent(value)}%",
    )


async def bar_percent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_manager(update, context):
        return

    if not context.args:
        await set_bar_percent(update, context, None)
        return

    raw = context.args[0].replace(",", ".")
    if not raw.replace(".", "", 1).isdigit():
        await reply_message(update.message,"Введите число от 0 до 100")
        return

    value = float(raw)
    await set_bar_percent(update, context, value)


async def test_half_month(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_manager(update, context):
        return

    settings = context.application.bot_data["settings"]
    api: LangameClient = context.application.bot_data["api"]
    storage: Storage = context.application.bot_data["storage"]

    report, error = build_current_half_month_test_report(api, storage, settings)
    if error:
        await _reply_manager(update, context, error)
        return
    if report is None:
        await _reply_manager(update, context, "Не удалось сформировать отчёт")
        return

    await notify_managers(context, report)
    await _reply_manager(update, context, f"{e('test')} Тестовое уведомление за полмесяца отправлено всем управляющим")
