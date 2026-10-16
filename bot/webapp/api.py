from __future__ import annotations

import logging
from datetime import timedelta
from io import BytesIO
from typing import Any, Awaitable, Callable

from aiohttp import web
from telegram import Bot
from telegram.constants import ParseMode

from bot.bar_sales import notify_admin_shift_closed
from bot.config import Settings
from bot.emojis import e
from bot.langame_api import LangameApiError, LangameClient
from bot.ledger import (
    compute_open_shift_stats,
    find_open_shift,
    find_open_shifts_for_linked_admins,
    get_admin_balance,
    get_period_summary,
    sync_admin_shifts,
    sync_all_admins,
    sync_shift_by_id,
)
from bot.messaging import send_via_bot
from bot.pay_period import current_pay_period, today_in_timezone
from bot.payroll_export import prepare_payroll_csv
from bot.roles import can_use_bot, has_manager_access, is_developer, is_env_manager, resolve_role, role_label
from bot.salary import resolve_langame_user
from bot.services import find_shift, get_bar_bonus_percent, set_bar_bonus_percent
from bot.storage import ROLE_ADMIN, Storage, UserLink
from bot.texts import (
    access_denied,
    admin_added_notify,
    admin_removed_notify,
    fine_cancelled_notify,
    fine_received,
    link_langame_first,
    link_langame_for_salary,
    not_registered,
)
from bot.webapp.auth import InitDataError, WebAppUser, validate_init_data
from bot.webapp.serializers import (
    admin_brief,
    balance_to_dict,
    earning_to_dict,
    fine_to_dict,
    money,
    open_shift_to_dict,
    period_summary_to_dict,
    period_to_dict,
    plain,
)

logger = logging.getLogger(__name__)

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]

SETTINGS_KEY = web.AppKey("settings", Settings)
STORAGE_KEY = web.AppKey("storage", Storage)
LANGAME_KEY = web.AppKey("langame", LangameClient)
BOT_KEY = web.AppKey("bot", Bot)
USER_KEY = web.RequestKey("tg_user", WebAppUser) if hasattr(web, "RequestKey") else "tg_user"

ACCESS_PUBLIC = "public"
ACCESS_USER = "user"
ACCESS_MANAGER = "manager"
ACCESS_DEVELOPER = "developer"

MANAGER_ONLY_TEXT = "Доступно только управляющему."
DEVELOPER_ONLY_TEXT = "Доступно только разработчику."


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = plain(message)
        self.status = status


def _settings(request: web.Request) -> Settings:
    return request.app[SETTINGS_KEY]


def _storage(request: web.Request) -> Storage:
    return request.app[STORAGE_KEY]


def _langame(request: web.Request) -> LangameClient:
    return request.app[LANGAME_KEY]


def _bot(request: web.Request) -> Bot:
    return request.app[BOT_KEY]


def _user(request: web.Request) -> WebAppUser:
    return request[USER_KEY]


async def _notify(request: web.Request, telegram_id: int, text: str) -> bool:
    try:
        await send_via_bot(_bot(request), telegram_id, text)
        return True
    except Exception as exc:
        logger.warning("Failed to notify %s: %s", telegram_id, exc)
        return False


async def _json_body(request: web.Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception as exc:
        raise ApiError("Некорректный запрос") from exc
    if not isinstance(body, dict):
        raise ApiError("Некорректный запрос")
    return body


def _parse_int(raw: Any, message: str) -> int:
    text = str(raw if raw is not None else "").strip()
    if not text.isdigit():
        raise ApiError(message)
    return int(text)


def _parse_amount(raw: Any, message: str) -> float:
    text = str(raw if raw is not None else "").strip().replace(",", ".")
    try:
        value = float(text)
    except ValueError as exc:
        raise ApiError(message) from exc
    if value != value or value < 0:
        raise ApiError(message)
    return value


def _require_admin_link(storage: Storage, telegram_id: int) -> UserLink:
    link = storage.get_link(telegram_id)
    if not link or link.role != ROLE_ADMIN:
        raise ApiError("Администратор не найден в боте", 404)
    return link


def _require_self_link(request: web.Request, *, langame: bool) -> UserLink:
    settings = _settings(request)
    storage = _storage(request)
    telegram_id = _user(request).telegram_id
    link = storage.get_link(telegram_id)
    if link is None:
        if has_manager_access(settings, storage, telegram_id):
            raise ApiError(link_langame_first(), 409)
        raise ApiError(not_registered(), 403)
    if langame and link.user_id == 0:
        raise ApiError(link_langame_for_salary(), 409)
    return link


def route(access: str) -> Callable[[Handler], Handler]:
    def decorator(handler: Handler) -> Handler:
        handler.access = access  # type: ignore[attr-defined]
        return handler

    return decorator


@web.middleware
async def api_middleware(request: web.Request, handler: Handler) -> web.StreamResponse:
    if not request.path.startswith("/api/"):
        return await handler(request)

    try:
        access = getattr(getattr(request.match_info, "handler", None), "access", ACCESS_USER)
        if access != ACCESS_PUBLIC:
            header = request.headers.get("Authorization", "")
            init_data = header[4:] if header.startswith("tma ") else ""
            try:
                user = validate_init_data(init_data, _settings(request).telegram_bot_token)
            except InitDataError as exc:
                raise ApiError(str(exc), 401) from exc
            request[USER_KEY] = user

            settings = _settings(request)
            storage = _storage(request)
            if access in (ACCESS_USER, ACCESS_MANAGER, ACCESS_DEVELOPER) and request.path != "/api/me":
                if not can_use_bot(settings, storage, user.telegram_id):
                    raise ApiError(access_denied(), 403)
            if access == ACCESS_MANAGER and not has_manager_access(settings, storage, user.telegram_id):
                raise ApiError(MANAGER_ONLY_TEXT, 403)
            if access == ACCESS_DEVELOPER and not is_developer(settings, user.telegram_id):
                raise ApiError(DEVELOPER_ONLY_TEXT, 403)

        return await handler(request)
    except ApiError as exc:
        return web.json_response({"error": exc.message}, status=exc.status)
    except web.HTTPException:
        raise
    except LangameApiError as exc:
        return web.json_response({"error": plain(str(exc))}, status=502)
    except Exception as exc:
        logger.exception("Web app API error on %s", request.path)
        return web.json_response({"error": f"Произошла ошибка: {exc}"}, status=500)


# ---------- Common ----------


def _me_payload(request: web.Request) -> dict:
    settings = _settings(request)
    storage = _storage(request)
    user = _user(request)
    telegram_id = user.telegram_id

    if not can_use_bot(settings, storage, telegram_id):
        return {
            "access": False,
            "telegram_id": telegram_id,
            "message": plain(access_denied()),
        }

    link = storage.get_link(telegram_id)
    manager = has_manager_access(settings, storage, telegram_id)
    developer = is_developer(settings, telegram_id)
    role = resolve_role(telegram_id, settings, storage)
    if link is not None:
        needs_link = link.user_id == 0
    else:
        needs_link = manager

    payload: dict[str, Any] = {
        "access": True,
        "telegram_id": telegram_id,
        "name": (link.username if link and link.username else None) or user.display_name,
        "role": role,
        "role_label": role_label(role),
        "is_manager": manager,
        "is_developer": developer,
        "is_admin": bool(link and link.role == ROLE_ADMIN) and not manager,
        "needs_link": needs_link,
        "langame_user_id": link.user_id if link and link.user_id else None,
        "email": link.email if link and link.user_id else None,
        "bar_percent": get_bar_bonus_percent(storage, settings),
        "fixed_salary": settings.fixed_salary,
        "fixed_cleaning": settings.fixed_cleaning,
        "balance": None,
    }
    today = today_in_timezone(settings.settlement_timezone)
    period = current_pay_period(today)
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    period_info = period_to_dict(period)
    period_info.update({
        "day_index": (today - period.date_from).days + 1,
        "days_total": (period.next_payout - period.date_from).days,
        "days_to_payout": (period.next_payout - today).days,
    })
    payload["today"] = today.isoformat()
    payload["period"] = period_info
    payload["week"] = {
        "days": [(week_start + timedelta(days=offset)).isoformat() for offset in range(7)],
        "shift_days": [],
    }

    def period_net(telegram_id: int) -> float:
        return get_period_summary(
            storage, telegram_id, period.date_from, period.date_to
        ).net_amount

    is_admin_link = link is not None and link.role == ROLE_ADMIN
    if is_admin_link:
        payload["balance"] = balance_to_dict(get_admin_balance(storage, telegram_id))
        payload["period_net"] = money(period_net(telegram_id))
    if manager:
        payload["week"]["shift_days"] = storage.list_shift_days(week_start, week_end)
        admins = storage.list_links(ROLE_ADMIN)
        payload["team_balance"] = money(sum(period_net(item.telegram_id) for item in admins))
        payload["stats"] = {
            "admins": len(admins),
            "active_fines": storage.count_active_fines(),
            "week_shift_days": len(payload["week"]["shift_days"]),
        }
    elif is_admin_link:
        payload["week"]["shift_days"] = storage.list_shift_days(week_start, week_end, telegram_id)
        payload["stats"] = {
            "period_shifts": len(
                storage.list_shift_earnings(telegram_id, period.date_from, period.date_to)
            ),
            "active_fines": storage.count_active_fines(telegram_id),
        }
    return payload


@route(ACCESS_USER)
async def get_me(request: web.Request) -> web.Response:
    return web.json_response(_me_payload(request))


@route(ACCESS_USER)
async def post_link(request: web.Request) -> web.Response:
    settings = _settings(request)
    storage = _storage(request)
    api = _langame(request)
    telegram_id = _user(request).telegram_id
    body = await _json_body(request)
    query = str(body.get("query", "")).strip()
    if not query:
        raise ApiError("Введите email или id администратора из LANGAME")

    existing = storage.get_link(telegram_id)
    if not existing and not has_manager_access(settings, storage, telegram_id):
        raise ApiError(not_registered(), 403)

    matched = resolve_langame_user(query, api.get_users())
    if not matched:
        raise ApiError("Администратор не найден. Проверьте email или id из LANGAME.", 404)

    owner = storage.get_link_by_user_id(matched.id)
    if owner is not None and owner.telegram_id != telegram_id:
        raise ApiError("Этот аккаунт LANGAME уже привязан к другому пользователю", 409)

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

    synced = 0
    sync_error = None
    link = storage.get_link(telegram_id)
    if link is not None and link.role == ROLE_ADMIN:
        synced, sync_error, _ = sync_admin_shifts(api, storage, settings, link)

    return web.json_response({
        "message": f"LANGAME привязан: {name} (id: {matched.id})",
        "synced": synced,
        "sync_error": plain(sync_error) if sync_error else None,
        "me": _me_payload(request),
    })


# ---------- Administrator ----------


@route(ACCESS_USER)
async def get_current_shift(request: web.Request) -> web.Response:
    settings = _settings(request)
    storage = _storage(request)
    api = _langame(request)
    telegram_id = _user(request).telegram_id

    if has_manager_access(settings, storage, telegram_id):
        shifts = []
        for shift, link in find_open_shifts_for_linked_admins(api, storage):
            stats = compute_open_shift_stats(
                api, storage, settings, link, shift, include_revenue_share=True
            )
            shifts.append({
                "admin": admin_brief(link),
                "shift": open_shift_to_dict(stats, settings),
            })
        return web.json_response({"mode": "manager", "shifts": shifts})

    link = _require_self_link(request, langame=True)
    _, error, _ = sync_admin_shifts(api, storage, settings, link)
    if error:
        raise ApiError(error, 502)

    open_shift = find_open_shift(api, link.user_id)
    if open_shift is not None:
        stats = compute_open_shift_stats(api, storage, settings, link, open_shift)
        return web.json_response({"mode": "open", "shift": open_shift_to_dict(stats, settings)})

    earnings = storage.list_shift_earnings(link.telegram_id, limit=1)
    if not earnings:
        return web.json_response({"mode": "none"})
    return web.json_response({
        "mode": "closed",
        "earning": earning_to_dict(storage, settings, earnings[0]),
    })


@route(ACCESS_USER)
async def get_half_month(request: web.Request) -> web.Response:
    settings = _settings(request)
    storage = _storage(request)
    api = _langame(request)
    link = _require_self_link(request, langame=True)

    _, error, _ = sync_admin_shifts(api, storage, settings, link)
    if error:
        raise ApiError(error, 502)

    period = current_pay_period(today_in_timezone(settings.settlement_timezone))
    summary = get_period_summary(storage, link.telegram_id, period.date_from, period.date_to)
    return web.json_response({
        "period": period_to_dict(period),
        "summary": period_summary_to_dict(storage, settings, summary),
        "balance": balance_to_dict(get_admin_balance(storage, link.telegram_id)),
    })


@route(ACCESS_USER)
async def get_my_fines(request: web.Request) -> web.Response:
    storage = _storage(request)
    link = _require_self_link(request, langame=False)
    fines = storage.list_fines(link.telegram_id, limit=50)
    return web.json_response({"fines": [fine_to_dict(storage, fine) for fine in fines]})


# ---------- Manager: team ----------


@route(ACCESS_MANAGER)
async def get_team(request: web.Request) -> web.Response:
    settings = _settings(request)
    storage = _storage(request)

    managers: list[dict] = []
    seen: set[int] = set()
    for telegram_id in sorted(settings.manager_telegram_ids):
        seen.add(telegram_id)
        link = storage.get_link(telegram_id)
        managers.append({
            "telegram_id": telegram_id,
            "name": Storage.admin_name(link, telegram_id),
            "removable": False,
        })
    for member in storage.list_staff_managers():
        if member.telegram_id in seen:
            continue
        seen.add(member.telegram_id)
        managers.append({
            "telegram_id": member.telegram_id,
            "name": member.username or str(member.telegram_id),
            "removable": not is_env_manager(settings, member.telegram_id)
            and not is_developer(settings, member.telegram_id),
        })

    admins = []
    for link in storage.list_links(ROLE_ADMIN):
        item = admin_brief(link)
        item["balance"] = money(get_admin_balance(storage, link.telegram_id).balance)
        admins.append(item)

    return web.json_response({
        "managers": managers,
        "developers": sorted(settings.developer_telegram_ids),
        "admins": admins,
    })


@route(ACCESS_MANAGER)
async def get_admin_card(request: web.Request) -> web.Response:
    settings = _settings(request)
    storage = _storage(request)
    api = _langame(request)
    telegram_id = _parse_int(request.match_info["telegram_id"], "Некорректный Telegram ID")
    link = _require_admin_link(storage, telegram_id)

    sync_error = None
    if link.user_id:
        _, sync_error, _ = sync_admin_shifts(api, storage, settings, link)

    period = current_pay_period(today_in_timezone(settings.settlement_timezone))
    summary = get_period_summary(storage, link.telegram_id, period.date_from, period.date_to)
    last = storage.list_shift_earnings(link.telegram_id, limit=1)
    fines = storage.list_fines(link.telegram_id, limit=10)

    card = admin_brief(link)
    card.update({
        "role_label": role_label(link.role),
        "balance": balance_to_dict(get_admin_balance(storage, link.telegram_id)),
        "period": period_to_dict(period),
        "summary": period_summary_to_dict(storage, settings, summary),
        "last_earning": earning_to_dict(storage, settings, last[0]) if last else None,
        "fines": [fine_to_dict(storage, fine) for fine in fines],
        "sync_error": plain(sync_error) if sync_error else None,
    })
    return web.json_response(card)


@route(ACCESS_MANAGER)
async def post_admin(request: web.Request) -> web.Response:
    settings = _settings(request)
    storage = _storage(request)
    body = await _json_body(request)
    name = str(body.get("name", "")).strip()
    if len(name) < 2:
        raise ApiError("Введите имя администратора (минимум 2 символа)")
    telegram_id = _parse_int(body.get("telegram_id"), "Telegram ID должен быть числом")

    if is_developer(settings, telegram_id):
        raise ApiError("Этот пользователь — разработчик.", 409)
    if has_manager_access(settings, storage, telegram_id):
        raise ApiError("Этот пользователь уже управляющий.", 409)
    existing = storage.get_link(telegram_id)
    if existing:
        raise ApiError(
            f"Администратор уже добавлен: {existing.username or existing.telegram_id}", 409
        )

    langame_query = str(body.get("langame_id") or "").strip()
    matched = None
    if langame_query:
        api = _langame(request)
        matched = resolve_langame_user(langame_query, api.get_users())
        if not matched:
            raise ApiError("Администратор не найден в LANGAME. Проверьте id.", 404)
        owner = storage.get_link_by_user_id(matched.id)
        if owner is not None:
            raise ApiError("Этот аккаунт LANGAME уже привязан к другому пользователю", 409)

    storage.register_admin(telegram_id=telegram_id, username=name)
    synced = 0
    sync_error = None
    if matched is not None:
        storage.attach_langame(
            telegram_id=telegram_id,
            user_id=matched.id,
            email=matched.email,
            langame_username=matched.username,
        )
        link = storage.get_link(telegram_id)
        if link is not None:
            synced, sync_error, _ = sync_admin_shifts(api, storage, settings, link)

    notified = await _notify(request, telegram_id, admin_added_notify(name))
    message = f"Администратор добавлен: {name} (TG: {telegram_id})"
    if matched is not None:
        message += f". LANGAME привязан: id {matched.id}"
    return web.json_response({
        "message": message,
        "notified": notified,
        "langame_user_id": matched.id if matched is not None else None,
        "synced": synced,
        "sync_error": plain(sync_error) if sync_error else None,
    })


@route(ACCESS_MANAGER)
async def delete_admin(request: web.Request) -> web.Response:
    settings = _settings(request)
    storage = _storage(request)
    telegram_id = _parse_int(request.match_info["telegram_id"], "Некорректный Telegram ID")
    link = _require_admin_link(storage, telegram_id)

    if is_developer(settings, telegram_id):
        raise ApiError("Нельзя убрать разработчика.", 409)
    if has_manager_access(settings, storage, telegram_id):
        raise ApiError("Нельзя убрать управляющего.", 409)

    name = Storage.admin_name(link)
    if not storage.remove_admin(telegram_id):
        raise ApiError("Не удалось убрать администратора.", 500)
    await _notify(request, telegram_id, admin_removed_notify())
    return web.json_response({"message": f"Администратор убран из бота: {name}"})


@route(ACCESS_DEVELOPER)
async def post_manager(request: web.Request) -> web.Response:
    settings = _settings(request)
    storage = _storage(request)
    body = await _json_body(request)
    name = str(body.get("name", "")).strip()
    if len(name) < 2:
        raise ApiError("Введите имя управляющего (минимум 2 символа)")
    telegram_id = _parse_int(body.get("telegram_id"), "Telegram ID должен быть числом")

    if is_developer(settings, telegram_id):
        raise ApiError("Этот пользователь уже разработчик.", 409)
    if has_manager_access(settings, storage, telegram_id):
        raise ApiError("Этот пользователь уже управляющий.", 409)

    storage.register_staff_manager(telegram_id=telegram_id, username=name)
    notified = await _notify(
        request,
        telegram_id,
        f"{e('party')} Вас добавили в Palace Adms как управляющего ({name}).\n"
        f"{e('wave')} Нажмите /start, чтобы открыть приложение.",
    )
    return web.json_response({
        "message": f"Управляющий добавлен: {name} (TG: {telegram_id})",
        "notified": notified,
    })


@route(ACCESS_DEVELOPER)
async def delete_manager(request: web.Request) -> web.Response:
    settings = _settings(request)
    storage = _storage(request)
    telegram_id = _parse_int(request.match_info["telegram_id"], "Некорректный Telegram ID")
    if is_developer(settings, telegram_id) or is_env_manager(settings, telegram_id):
        raise ApiError("Этот управляющий задан в настройках сервера (.env)", 409)
    if not storage.remove_staff_manager(telegram_id):
        raise ApiError("Управляющий не найден", 404)
    return web.json_response({"message": f"Управляющий {telegram_id} снят"})


# ---------- Manager: money ----------


@route(ACCESS_MANAGER)
async def get_payroll(request: web.Request) -> web.Response:
    settings = _settings(request)
    storage = _storage(request)
    api = _langame(request)
    period = current_pay_period(today_in_timezone(settings.settlement_timezone))

    _, sync_error = sync_all_admins(api, storage, settings)
    if sync_error:
        raise ApiError(sync_error, 502)

    rows = []
    total = 0.0
    for link in storage.list_links(ROLE_ADMIN):
        if not link.user_id:
            continue
        summary = get_period_summary(storage, link.telegram_id, period.date_from, period.date_to)
        balance = get_admin_balance(storage, link.telegram_id)
        rows.append({
            "telegram_id": link.telegram_id,
            "name": Storage.admin_name(link),
            "shifts": len(summary.earnings),
            "bar_sales": money(summary.bar_sales_total),
            "gross": money(summary.gross_earned),
            "fines": money(summary.fines_total),
            "net": money(summary.net_amount),
            "balance": money(balance.balance),
        })
        total += summary.net_amount

    rows.sort(key=lambda item: item["net"], reverse=True)
    return web.json_response({
        "period": period_to_dict(period),
        "rows": rows,
        "total": money(total),
    })


@route(ACCESS_MANAGER)
async def post_payroll_export(request: web.Request) -> web.Response:
    settings = _settings(request)
    storage = _storage(request)
    api = _langame(request)
    period = current_pay_period(today_in_timezone(settings.settlement_timezone))

    csv_content, error = await prepare_payroll_csv(api, storage, settings, period)
    if error or csv_content is None:
        raise ApiError(error or "Не удалось сформировать ведомость", 502)

    filename = f"vedomost_{period.cycle_key}.csv"
    buffer = BytesIO(csv_content.encode("utf-8-sig"))
    buffer.name = filename
    caption = (
        f"{e('chart')} Ведомость за {period.half_label}\n"
        f"{e('date')} {period.date_from.strftime('%d.%m.%Y')} — "
        f"{period.date_to.strftime('%d.%m.%Y')}"
    )
    try:
        await _bot(request).send_document(
            chat_id=_user(request).telegram_id,
            document=buffer,
            filename=filename,
            caption=caption,
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        raise ApiError(f"Не удалось отправить файл в чат: {exc}", 502) from exc
    return web.json_response({"message": "Файл ведомости отправлен в чат с ботом"})


@route(ACCESS_MANAGER)
async def get_leaderboard(request: web.Request) -> web.Response:
    settings = _settings(request)
    storage = _storage(request)
    api = _langame(request)
    period = current_pay_period(today_in_timezone(settings.settlement_timezone))

    _, sync_error = sync_all_admins(api, storage, settings)
    if sync_error:
        raise ApiError(sync_error, 502)

    rows = []
    for link in storage.list_links(ROLE_ADMIN):
        if link.user_id == 0:
            continue
        earnings = storage.list_shift_earnings(link.telegram_id, period.date_from, period.date_to)
        total = sum(item.bar_sales for item in earnings)
        if total > 0:
            rows.append({
                "telegram_id": link.telegram_id,
                "name": Storage.admin_name(link),
                "bar_sales": money(total),
                "shifts": len(earnings),
            })
    rows.sort(key=lambda item: item["bar_sales"], reverse=True)
    return web.json_response({"period": period_to_dict(period), "rows": rows})


@route(ACCESS_MANAGER)
async def get_bar_percent(request: web.Request) -> web.Response:
    return web.json_response({
        "value": get_bar_bonus_percent(_storage(request), _settings(request)),
    })


@route(ACCESS_MANAGER)
async def put_bar_percent(request: web.Request) -> web.Response:
    body = await _json_body(request)
    value = _parse_amount(body.get("value"), "Введите число от 0 до 100")
    try:
        set_bar_bonus_percent(_storage(request), value)
    except ValueError as exc:
        raise ApiError(str(exc)) from exc
    return web.json_response({
        "value": get_bar_bonus_percent(_storage(request), _settings(request)),
        "message": "Процент с бара изменён",
    })


@route(ACCESS_MANAGER)
async def post_broadcast(request: web.Request) -> web.Response:
    storage = _storage(request)
    body = await _json_body(request)
    text = str(body.get("text", "")).strip()
    if not text:
        raise ApiError("Введите текст рассылки")

    admins = storage.list_links(ROLE_ADMIN)
    if not admins:
        raise ApiError("Нет зарегистрированных администраторов", 404)

    sent = 0
    for link in admins:
        try:
            await _bot(request).send_message(
                chat_id=link.telegram_id,
                text=f"Сообщение от управляющего:\n\n{text}",
            )
            sent += 1
        except Exception as exc:
            logger.warning("Broadcast to %s failed: %s", link.telegram_id, exc)
    return web.json_response({
        "sent": sent,
        "total": len(admins),
        "message": f"Отправлено {sent} из {len(admins)} администраторов",
    })


# ---------- Manager: fines ----------


@route(ACCESS_MANAGER)
async def get_fines(request: web.Request) -> web.Response:
    storage = _storage(request)
    raw = request.query.get("telegram_id", "").strip()
    telegram_id = _parse_int(raw, "Некорректный Telegram ID") if raw else None
    fines = storage.list_fines(telegram_id, limit=50)
    return web.json_response({"fines": [fine_to_dict(storage, fine) for fine in fines]})


@route(ACCESS_MANAGER)
async def post_fine(request: web.Request) -> web.Response:
    storage = _storage(request)
    body = await _json_body(request)
    telegram_id = _parse_int(body.get("telegram_id"), "Выберите администратора")
    link = _require_admin_link(storage, telegram_id)
    amount = _parse_amount(body.get("amount"), "Сумма должна быть числом")
    if amount <= 0:
        raise ApiError("Сумма должна быть больше нуля")
    reason = str(body.get("reason", "")).strip()
    if not reason:
        raise ApiError("Укажите причину штрафа")
    shift_raw = str(body.get("shift_id") or "").strip()
    shift_id = _parse_int(shift_raw, "Id смены должен быть числом") if shift_raw else None

    fine_id = storage.add_fine(
        telegram_id=link.telegram_id,
        amount=amount,
        reason=reason,
        created_by=_user(request).telegram_id,
        shift_id=shift_id,
    )
    notified = await _notify(
        request, link.telegram_id, fine_received(fine_id, amount, reason, shift_id=shift_id)
    )
    return web.json_response({
        "message": f"Штраф #{fine_id} выписан: {Storage.admin_name(link)}",
        "fine": fine_to_dict(storage, storage.get_fine(fine_id)),
        "notified": notified,
    })


@route(ACCESS_MANAGER)
async def delete_fine(request: web.Request) -> web.Response:
    storage = _storage(request)
    fine_id = _parse_int(request.match_info["fine_id"], "Номер штрафа должен быть числом")
    fine = storage.get_fine(fine_id)
    if fine is None:
        raise ApiError("Штраф не найден.", 404)
    if not storage.cancel_fine(fine_id):
        raise ApiError("Штраф уже отменён.", 409)
    await _notify(request, fine.telegram_id, fine_cancelled_notify(fine_id, fine.amount, fine.reason))
    return web.json_response({"message": f"Штраф #{fine_id} снят"})


# ---------- Manager: shift report ----------


@route(ACCESS_MANAGER)
async def get_shift_report(request: web.Request) -> web.Response:
    settings = _settings(request)
    storage = _storage(request)
    api = _langame(request)
    shift_id = _parse_int(request.match_info["shift_id"], "Введите число — id смены")

    shift = find_shift(api, shift_id)
    if not shift:
        raise ApiError(f"Смена #{shift_id} не найдена в LANGAME", 404)

    link = storage.get_link_by_user_id(shift.user_id)
    if not link:
        raise ApiError(f"Смена #{shift_id} — администратор не зарегистрирован в боте", 404)

    if shift.date_stop is None:
        stats = compute_open_shift_stats(
            api, storage, settings, link, shift, include_revenue_share=True
        )
        return web.json_response({
            "admin": admin_brief(link),
            "open": True,
            "shift": open_shift_to_dict(stats, settings),
        })

    earning, error, fixed = sync_shift_by_id(api, storage, settings, link, shift_id)
    if error:
        raise ApiError(error, 409)
    if earning is None:
        raise ApiError(f"Смена #{shift_id} не найдена", 404)
    if fixed is not None:
        await notify_admin_shift_closed(_bot(request), storage, link.telegram_id, shift_id)

    return web.json_response({
        "admin": admin_brief(link),
        "open": False,
        "earning": earning_to_dict(storage, settings, earning),
    })


def register_routes(app: web.Application) -> None:
    r = app.router
    r.add_get("/api/me", get_me)
    r.add_post("/api/link", post_link)
    r.add_get("/api/shift/current", get_current_shift)
    r.add_get("/api/half-month", get_half_month)
    r.add_get("/api/my/fines", get_my_fines)

    r.add_get("/api/team", get_team)
    r.add_post("/api/admins", post_admin)
    r.add_get("/api/admins/{telegram_id}", get_admin_card)
    r.add_delete("/api/admins/{telegram_id}", delete_admin)
    r.add_post("/api/managers", post_manager)
    r.add_delete("/api/managers/{telegram_id}", delete_manager)

    r.add_get("/api/payroll", get_payroll)
    r.add_post("/api/payroll/export", post_payroll_export)
    r.add_get("/api/leaderboard", get_leaderboard)
    r.add_get("/api/settings/bar-percent", get_bar_percent)
    r.add_put("/api/settings/bar-percent", put_bar_percent)
    r.add_post("/api/broadcast", post_broadcast)

    r.add_get("/api/fines", get_fines)
    r.add_post("/api/fines", post_fine)
    r.add_delete("/api/fines/{fine_id}", delete_fine)

    r.add_get("/api/shifts/{shift_id}/report", get_shift_report)
