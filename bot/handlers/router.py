from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.config import Settings
from bot.handlers import admin, manager
from bot.keyboards import (
    BTN_ADD_ADMIN,
    BTN_ADD_MANAGER,
    BTN_ADMIN_CARD,
    BTN_BROADCAST,
    BTN_CANCEL,
    BTN_FINE,
    BTN_REMOVE_FINE,
    BTN_FINES_ALL,
    BTN_REMOVE_ADMIN,
    BTN_HELP,
    BTN_HOME,
    BTN_LEADERBOARD,
    BTN_BAR_PERCENT,
    BTN_HALF_MONTH,
    BTN_LINK,
    BTN_MY_FINES,
    BTN_NET,
    BTN_PAYROLL,
    BTN_PROFILE,
    BTN_SALARY,
    BTN_HALF_MONTH_TEST,
    BTN_SHIFT_REPORT,
    BTN_TEAM,
    STATE_ADD_ADMIN_NAME,
    STATE_ADD_ADMIN_TG,
    STATE_ADD_MANAGER_NAME,
    STATE_ADD_MANAGER_TG,
    STATE_ADMIN_QUERY,
    STATE_BROADCAST,
    STATE_BAR_PERCENT,
    STATE_FINE_ADMIN,
    STATE_FINE_AMOUNT,
    STATE_FINE_REASON,
    STATE_LINK,
    STATE_REMOVE_FINE_ID,
    STATE_REMOVE_ADMIN_QUERY,
    STATE_SHIFT_ID,
    STATE_SHIFT_REPORT,
    build_cancel_keyboard,
    build_main_keyboard,
    clear_state,
    get_draft,
    match_button,
    normalize_button_text,
)
from bot.messaging import reply as reply_message, send as send_message
from bot.emojis import e
from bot.langame_api import LangameApiError, LangameClient
from bot.services import format_percent, get_bar_bonus_percent
from bot.roles import (
    can_use_bot,
    deny_access,
    has_manager_access,
    is_developer,
    require_access,
    require_developer,
    require_manager,
)
from bot.salary import format_money, resolve_langame_user
from bot.storage import ROLE_ADMIN, Storage
from bot.texts import (
    action_cancelled,
    admin_added,
    admin_added_notify,
    fine_cancelled,
    fine_cancelled_notify,
    fine_already_cancelled,
    fine_issued,
    fine_not_found,
    fine_received,
    help_admin_section,
    help_developer_section,
    help_header,
    help_manager_section,
    manager_only_fines,
    not_registered,
    remove_admin_prompt,
    remove_fine_prompt,
    welcome_admin,
    welcome_developer,
    welcome_guest,
    welcome_manager,
    unknown_command,
)

MANAGER_ONLY_STATES = {
    STATE_ADD_ADMIN_NAME,
    STATE_ADD_ADMIN_TG,
    STATE_FINE_ADMIN,
    STATE_FINE_AMOUNT,
    STATE_FINE_REASON,
    STATE_BROADCAST,
    STATE_BAR_PERCENT,
    STATE_ADMIN_QUERY,
    STATE_SHIFT_REPORT,
    STATE_REMOVE_FINE_ID,
    STATE_REMOVE_ADMIN_QUERY,
}


DEVELOPER_ONLY_STATES = {
    STATE_ADD_MANAGER_NAME,
    STATE_ADD_MANAGER_TG,
}


async def reply_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    *,
    with_menu: bool = False,
    reply_markup=None,
) -> None:
    markup = reply_markup
    if with_menu:
        settings: Settings = context.application.bot_data["settings"]
        storage: Storage = context.application.bot_data["storage"]
        markup = build_main_keyboard(update.effective_user.id, settings, storage)
    await reply_message(update.message, text, reply_markup=markup)


async def reply_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    await reply_text(update, context, text, with_menu=True)


async def _deny_manager_only(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await reply_menu(update, context, manager_only_fines())


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_state(context)
    settings: Settings = context.application.bot_data["settings"]
    storage: Storage = context.application.bot_data["storage"]
    telegram_id = update.effective_user.id

    if not can_use_bot(settings, storage, telegram_id):
        await deny_access(update)
        return

    link = storage.get_link(telegram_id)
    staff_access = has_manager_access(settings, storage, telegram_id)
    developer_access = is_developer(settings, telegram_id)

    if developer_access:
        text = welcome_developer()
    elif staff_access:
        text = welcome_manager()
    elif link:
        bar_percent = get_bar_bonus_percent(storage, settings)
        text = welcome_admin(
            langame_linked=link.user_id != 0,
            bar_bonus_percent=bar_percent,
            fixed_salary=settings.fixed_salary,
        )
    else:
        text = welcome_guest()

    keyboard = build_main_keyboard(telegram_id, settings, storage)
    await reply_message(update.message, text, reply_markup=keyboard)


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_access(update, context):
        return

    settings: Settings = context.application.bot_data["settings"]
    storage: Storage = context.application.bot_data["storage"]
    link = storage.get_link(update.effective_user.id)
    staff_access = has_manager_access(settings, storage, update.effective_user.id)
    developer_access = is_developer(settings, update.effective_user.id)

    bar_percent = get_bar_bonus_percent(storage, settings)
    lines = [
        help_header(
            bar_bonus_percent=bar_percent,
            fixed_salary=settings.fixed_salary,
        ),
        *help_admin_section(),
    ]
    if staff_access:
        lines.extend(help_manager_section())
    if developer_access:
        lines.extend(help_developer_section())

    keyboard = build_main_keyboard(update.effective_user.id, settings, storage)
    await reply_message(update.message, "\n".join(lines), reply_markup=keyboard)


async def _process_link(update: Update, context: ContextTypes.DEFAULT_TYPE, email: str) -> None:
    settings: Settings = context.application.bot_data["settings"]
    api: LangameClient = context.application.bot_data["api"]
    storage: Storage = context.application.bot_data["storage"]
    telegram_id = update.effective_user.id

    if not can_use_bot(settings, storage, telegram_id):
        await deny_access(update)
        return

    existing = storage.get_link(telegram_id)
    if not existing and not has_manager_access(settings, storage, telegram_id):
        await reply_menu(update, context, not_registered())
        return

    try:
        users = api.get_users()
    except LangameApiError as exc:
        await reply_menu(update, context, str(exc))
        return

    matched = resolve_langame_user(email, users)
    if not matched:
        await reply_menu(
            update,
            context,
            "Администратор не найден. Проверьте email или id из LANGAME.",
        )
        return

    if existing:
        storage.attach_langame(
            telegram_id=telegram_id,
            user_id=matched.id,
            email=matched.email,
            langame_username=matched.username,
        )
        name = existing.username or matched.username or matched.email
    else:
        storage.link_admin(
            telegram_id=telegram_id,
            user_id=matched.id,
            email=matched.email,
            username=matched.username or matched.email,
            role=ROLE_ADMIN,
        )
        name = matched.username or matched.email

    await reply_menu(
        update,
        context,
        f"{e('link')} LANGAME привязан: {name} (id: {matched.id})",
    )


async def _process_add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_manager(update, context):
        clear_state(context)
        return

    settings: Settings = context.application.bot_data["settings"]
    storage: Storage = context.application.bot_data["storage"]
    draft = get_draft(context)
    name = draft.get("admin_name", "").strip()
    tg_raw = draft.get("admin_tg", "").strip()

    if not name:
        clear_state(context)
        await reply_menu(update, context, "Имя не может быть пустым.")
        return

    if not tg_raw.isdigit():
        clear_state(context)
        await reply_menu(update, context, "Telegram ID должен быть числом.")
        return

    telegram_id = int(tg_raw)
    if is_developer(settings, telegram_id):
        clear_state(context)
        await reply_menu(update, context, "Этот пользователь — разработчик.")
        return
    if has_manager_access(settings, storage, telegram_id):
        clear_state(context)
        await reply_menu(update, context, "Этот пользователь уже управляющий.")
        return

    existing = storage.get_link(telegram_id)
    if existing:
        clear_state(context)
        await reply_menu(
            update,
            context,
            f"Администратор уже добавлен: {existing.username or existing.telegram_id}",
        )
        return

    storage.register_admin(telegram_id=telegram_id, username=name)
    clear_state(context)
    await reply_menu(
        update,
        context,
        admin_added(name, telegram_id),
    )

    try:
        await send_message(context, telegram_id, admin_added_notify(name))
    except Exception:
        pass


async def _process_add_manager(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_developer(update, context):
        clear_state(context)
        return

    settings: Settings = context.application.bot_data["settings"]
    storage: Storage = context.application.bot_data["storage"]
    draft = get_draft(context)
    name = draft.get("manager_name", "").strip()
    tg_raw = draft.get("manager_tg", "").strip()

    if not name:
        clear_state(context)
        await reply_menu(update, context, "Имя не может быть пустым.")
        return

    if not tg_raw.isdigit():
        clear_state(context)
        await reply_menu(update, context, "Telegram ID должен быть числом.")
        return

    telegram_id = int(tg_raw)
    if is_developer(settings, telegram_id):
        clear_state(context)
        await reply_menu(update, context, "Этот пользователь уже разработчик.")
        return
    if has_manager_access(settings, storage, telegram_id):
        clear_state(context)
        await reply_menu(update, context, "Этот пользователь уже управляющий.")
        return

    storage.register_staff_manager(telegram_id=telegram_id, username=name)
    clear_state(context)
    await reply_menu(
        update,
        context,
        f"Управляющий добавлен:\n{name}\nTelegram ID: {telegram_id}",
    )

    try:
        await send_message(
            context,
            telegram_id,
            f"Вас добавили в бот Palace Adms как управляющего ({name}).\n"
            "Нажмите /start для входа.",
        )
    except Exception:
        pass


async def _process_fine(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_manager(update, context):
        clear_state(context)
        return

    draft = get_draft(context)
    storage: Storage = context.application.bot_data["storage"]
    link = storage.resolve_bot_admin(draft["admin"])
    if not link:
        clear_state(context)
        await reply_menu(update, context, "Администратор не найден в боте")
        return

    fine_id = storage.add_fine(
        telegram_id=link.telegram_id,
        amount=float(draft["amount"]),
        reason=draft["reason"],
        created_by=update.effective_user.id,
        shift_id=draft.get("shift_id"),
    )
    name = Storage.admin_name(link)
    clear_state(context)
    await reply_menu(
        update,
        context,
        fine_issued(
            fine_id,
            name,
            float(draft["amount"]),
            draft["reason"],
            shift_id=draft.get("shift_id"),
        ),
    )

    try:
        await send_message(
            context,
            link.telegram_id,
            fine_received(
                fine_id,
                float(draft["amount"]),
                draft["reason"],
                shift_id=draft.get("shift_id"),
            ),
        )
    except Exception:
        pass


async def _process_remove_fine(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_manager(update, context):
        clear_state(context)
        return

    draft = get_draft(context)
    fine_id_raw = str(draft.get("fine_id", "")).strip()
    clear_state(context)

    if not fine_id_raw.isdigit():
        await reply_menu(update, context, f"{e('info')} Номер штрафа должен быть числом.")
        return

    storage: Storage = context.application.bot_data["storage"]
    fine_id = int(fine_id_raw)
    fine = storage.get_fine(fine_id)
    if fine is None:
        await reply_menu(update, context, fine_not_found())
        return

    if not storage.cancel_fine(fine_id):
        await reply_menu(update, context, fine_already_cancelled())
        return

    link = storage.get_link(fine.telegram_id)
    name = Storage.admin_name(link, fine.telegram_id)
    await reply_menu(
        update,
        context,
        fine_cancelled(fine_id, name, fine.amount, fine.reason),
    )

    try:
        await send_message(context, fine.telegram_id, fine_cancelled_notify(fine_id, fine.amount, fine.reason))
    except Exception:
        pass


async def _process_remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_manager(update, context):
        clear_state(context)
        return

    draft = get_draft(context)
    query = str(draft.get("admin", "")).strip()
    clear_state(context)
    await manager.remove_admin(update, context, query=query)


async def _process_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    if not await require_manager(update, context):
        clear_state(context)
        return

    storage: Storage = context.application.bot_data["storage"]
    admins = [link for link in storage.list_links(ROLE_ADMIN)]
    clear_state(context)

    if not admins:
        await reply_menu(update, context, "Нет привязанных администраторов")
        return

    sent = 0
    for link in admins:
        try:
            await send_message(context, link.telegram_id, f"Сообщение от управляющего:\n\n{text}")
            sent += 1
        except Exception:
            pass

    await reply_menu(update, context, f"Отправлено {sent} из {len(admins)} администраторов")


async def handle_state_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    state = context.user_data.get("state")
    if not state:
        return False

    if state in DEVELOPER_ONLY_STATES:
        if not await require_developer(update, context):
            clear_state(context)
            return True

    if state in MANAGER_ONLY_STATES:
        if not await require_manager(update, context):
            clear_state(context)
            return True

    text = (update.message.text or "").strip()
    if normalize_button_text(text) == normalize_button_text(BTN_CANCEL):
        clear_state(context)
        await reply_menu(update, context, action_cancelled())
        return True

    if match_button(text) is not None:
        return False

    draft = get_draft(context)

    if state == STATE_ADD_ADMIN_NAME:
        if len(text) < 2:
            await reply_text(
                update, context, "Введите имя администратора (минимум 2 символа):",
                reply_markup=build_cancel_keyboard(),
            )
            return True
        draft["admin_name"] = text
        context.user_data["state"] = STATE_ADD_ADMIN_TG
        await reply_text(
            update, context, "Введите Telegram ID нового администратора:",
            reply_markup=build_cancel_keyboard(),
        )
        return True

    if state == STATE_ADD_ADMIN_TG:
        draft["admin_tg"] = text
        await _process_add_admin(update, context)
        return True

    if state == STATE_ADD_MANAGER_NAME:
        if len(text) < 2:
            await reply_text(
                update, context, "Введите имя управляющего (минимум 2 символа):",
                reply_markup=build_cancel_keyboard(),
            )
            return True
        draft["manager_name"] = text
        context.user_data["state"] = STATE_ADD_MANAGER_TG
        await reply_text(
            update, context, "Введите Telegram ID нового управляющего:",
            reply_markup=build_cancel_keyboard(),
        )
        return True

    if state == STATE_ADD_MANAGER_TG:
        draft["manager_tg"] = text
        await _process_add_manager(update, context)
        return True

    if state == STATE_LINK:
        clear_state(context)
        await _process_link(update, context, text)
        return True

    if state == STATE_SHIFT_ID:
        if not text.isdigit():
            await reply_text(
                update, context, "Введите число — id смены:",
                reply_markup=build_cancel_keyboard(),
            )
            return True
        clear_state(context)
        await admin.shift(update, context, shift_id=int(text))
        return True

    if state == STATE_SHIFT_REPORT:
        if not text.isdigit():
            await reply_text(
                update, context, "Введите id смены:",
                reply_markup=build_cancel_keyboard(),
            )
            return True
        clear_state(context)
        await manager.shiftreport(update, context, shift_id=int(text))
        return True

    if state == STATE_ADMIN_QUERY:
        clear_state(context)
        await manager.admin_card(update, context, query=text)
        return True

    if state == STATE_FINE_ADMIN:
        draft["admin"] = text
        context.user_data["state"] = STATE_FINE_AMOUNT
        await reply_text(
            update, context, "Введите сумму штрафа:",
            reply_markup=build_cancel_keyboard(),
        )
        return True

    if state == STATE_FINE_AMOUNT:
        amount_raw = text.replace(",", ".")
        if not amount_raw.replace(".", "", 1).isdigit():
            await reply_text(
                update, context, "Сумма должна быть числом:",
                reply_markup=build_cancel_keyboard(),
            )
            return True
        draft["amount"] = float(amount_raw)
        context.user_data["state"] = STATE_FINE_REASON
        await reply_text(
            update, context, "Введите причину штрафа:",
            reply_markup=build_cancel_keyboard(),
        )
        return True

    if state == STATE_FINE_REASON:
        draft["reason"] = text
        await _process_fine(update, context)
        return True

    if state == STATE_REMOVE_FINE_ID:
        if not text.isdigit():
            await reply_text(
                update, context, "Введите номер штрафа (#id):",
                reply_markup=build_cancel_keyboard(),
            )
            return True
        draft["fine_id"] = text
        await _process_remove_fine(update, context)
        return True

    if state == STATE_REMOVE_ADMIN_QUERY:
        draft["admin"] = text
        await _process_remove_admin(update, context)
        return True

    if state == STATE_BROADCAST:
        await _process_broadcast(update, context, text)
        return True

    if state == STATE_BAR_PERCENT:
        raw = text.replace(",", ".")
        if not raw.replace(".", "", 1).isdigit():
            await reply_text(
                update, context, "Введите число от 0 до 100:",
                reply_markup=build_cancel_keyboard(),
            )
            return True
        value = float(raw)
        if value < 0 or value > 100:
            await reply_text(
                update, context, "Процент должен быть от 0 до 100:",
                reply_markup=build_cancel_keyboard(),
            )
            return True
        clear_state(context)
        await manager.set_bar_percent(update, context, value)
        return True

    return False


async def _manager_action(update: Update, context: ContextTypes.DEFAULT_TYPE, action) -> None:
    if not await require_manager(update, context):
        return
    try:
        await action(update, context)
    except Exception as exc:
        await reply_menu(update, context, f"Ошибка: {exc}")


async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await _handle_button(update, context)
    except Exception as exc:
        clear_state(context)
        await reply_menu(update, context, f"Произошла ошибка: {exc}")


async def _handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    raw_text = update.message.text or ""
    normalized = normalize_button_text(raw_text)
    button = match_button(raw_text)

    if button == BTN_HOME or normalized == "/start":
        clear_state(context)
        await handle_start(update, context)
        return

    if button == BTN_HELP or normalized == "/help":
        clear_state(context)
        await handle_help(update, context)
        return

    if button is not None:
        clear_state(context)
    elif await handle_state_input(update, context):
        return

    if not await require_access(update, context):
        return

    text = button or raw_text

    if text == BTN_SALARY:
        await admin.salary(update, context)
        return

    if text == BTN_HALF_MONTH:
        await admin.half_month(update, context)
        return

    if text == BTN_NET:
        await admin.net(update, context)
        return

    if text == BTN_MY_FINES:
        await admin.myfines(update, context)
        return

    if text == BTN_PROFILE:
        await admin.me(update, context)
        return

    if text == BTN_LINK:
        context.user_data["state"] = STATE_LINK
        get_draft(context)
        await reply_text(
            update,
            context,
            "Введите email или id администратора из LANGAME:",
            reply_markup=build_cancel_keyboard(),
        )
        return

    if text == BTN_FINE or text == BTN_REMOVE_FINE or text == BTN_REMOVE_ADMIN:
        settings: Settings = context.application.bot_data["settings"]
        storage: Storage = context.application.bot_data["storage"]
        if not has_manager_access(settings, storage, update.effective_user.id):
            await _deny_manager_only(update, context)
            return

    if text == BTN_TEAM:
        await _manager_action(update, context, manager.team)
        return

    if text == BTN_ADD_ADMIN:
        if not await require_manager(update, context):
            return
        context.user_data["state"] = STATE_ADD_ADMIN_NAME
        get_draft(context)
        await reply_text(
            update,
            context,
            "Введите имя нового администратора:",
            reply_markup=build_cancel_keyboard(),
        )
        return

    if text == BTN_ADD_MANAGER:
        if not await require_developer(update, context):
            return
        context.user_data["state"] = STATE_ADD_MANAGER_NAME
        get_draft(context)
        await reply_text(
            update,
            context,
            "Введите имя нового управляющего:",
            reply_markup=build_cancel_keyboard(),
        )
        return

    if text == BTN_PAYROLL:
        await _manager_action(update, context, manager.payroll)
        return

    if text == BTN_LEADERBOARD:
        await _manager_action(update, context, manager.leaderboard)
        return

    if text == BTN_BAR_PERCENT:
        if not await require_manager(update, context):
            return
        settings = context.application.bot_data["settings"]
        storage: Storage = context.application.bot_data["storage"]
        current = get_bar_bonus_percent(storage, settings)
        context.user_data["state"] = STATE_BAR_PERCENT
        await reply_text(
            update,
            context,
            f"{e('burger')} Текущий процент с бара: {format_percent(current)}%\n\n"
            "Введите новый процент (0–100):",
            reply_markup=build_cancel_keyboard(),
        )
        return

    if text == BTN_HALF_MONTH_TEST:
        await _manager_action(update, context, manager.test_half_month)
        return

    if text == BTN_FINES_ALL:
        await _manager_action(update, context, manager.fines_list)
        return

    if text == BTN_BROADCAST:
        if not await require_manager(update, context):
            return
        context.user_data["state"] = STATE_BROADCAST
        await reply_text(
            update,
            context,
            "Введите текст рассылки для всех администраторов:",
            reply_markup=build_cancel_keyboard(),
        )
        return

    if text == BTN_FINE:
        context.user_data["state"] = STATE_FINE_ADMIN
        get_draft(context)
        await reply_text(
            update,
            context,
            "Кому штраф? Введите имя или Telegram ID:",
            reply_markup=build_cancel_keyboard(),
        )
        return

    if text == BTN_REMOVE_FINE:
        if not await require_manager(update, context):
            return
        storage: Storage = context.application.bot_data["storage"]
        records = storage.list_fines(limit=10)
        lines = ["🗑 Введите номер штрафа (#id):"]
        if records:
            lines.insert(0, f"{e('warning')} Последние штрафы:")
            for record in records:
                admin_link = storage.get_link(record.telegram_id)
                admin_name = Storage.admin_name(admin_link, record.telegram_id)
                lines.append(f"#{record.id}: {admin_name}, −{format_money(record.amount)}")
            lines.append("")
        context.user_data["state"] = STATE_REMOVE_FINE_ID
        get_draft(context)
        await reply_text(
            update,
            context,
            remove_fine_prompt(lines),
            reply_markup=build_cancel_keyboard(),
        )
        return

    if text == BTN_REMOVE_ADMIN:
        if not await require_manager(update, context):
            return
        storage: Storage = context.application.bot_data["storage"]
        admins = storage.list_links(ROLE_ADMIN)
        lines = ["🗑 Кого убрать? Введите имя или Telegram ID:"]
        if admins:
            lines.insert(0, f"{e('person')} Администраторы в боте:")
            for link in admins:
                name = Storage.admin_name(link)
                lines.append(f"• {name} — TG: {link.telegram_id}")
            lines.append("")
        context.user_data["state"] = STATE_REMOVE_ADMIN_QUERY
        get_draft(context)
        await reply_text(
            update,
            context,
            remove_admin_prompt(lines),
            reply_markup=build_cancel_keyboard(),
        )
        return

    if text == BTN_ADMIN_CARD:
        if not await require_manager(update, context):
            return
        context.user_data["state"] = STATE_ADMIN_QUERY
        await reply_text(
            update,
            context,
            "Введите имя или Telegram ID администратора:",
            reply_markup=build_cancel_keyboard(),
        )
        return

    if text == BTN_SHIFT_REPORT:
        if not await require_manager(update, context):
            return
        context.user_data["state"] = STATE_SHIFT_REPORT
        await reply_text(
            update,
            context,
            "Введите id смены:",
            reply_markup=build_cancel_keyboard(),
        )
        return

    await reply_menu(update, context, unknown_command())
