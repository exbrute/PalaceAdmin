"""User-facing bot messages with themed custom emoji."""

from bot.emojis import e, h
from bot.salary import format_money
from bot.services import format_percent


def bar_bonus_added(
    amount: float,
    bar_bonus_percent: float,
    sale_amount: float,
    product_name: str,
    product_count: int,
) -> str:
    item_name = product_name.strip() or "Товар без названия"
    return (
        f"{e('money_bag')} Вам добавлено {h(format_money(amount))}! "
        f"({h(format_percent(bar_bonus_percent))}% от бара) {e('burger')}\n"
        f"{e('memo')} Товар: {h(item_name)} ×{h(product_count)}\n"
        f"{e('burger')} Продано из бара: {h(format_money(sale_amount))}"
    )


def shift_fixed_added(amount: float) -> str:
    return (
        f"{e('check')} За смену начислено {h(format_money(amount))}!\n"
        f"{e('gear')} Фикс за закрытую смену"
    )


def admin_shift_closed(
    *,
    shift_id: int,
    fixed: float,
    bar_bonus: float,
    fines: float = 0,
) -> str:
    lines = [
        f"{e('check')} Смена #{h(shift_id)} закрыта",
        "",
        f"{e('money_bag')} Начислено: {h(format_money(fixed))} + {h(format_money(bar_bonus))} с бара",
    ]
    if fines > 0:
        lines.append(f"{e('warning')} Штрафы: −{h(format_money(fines))}")
        net = fixed + bar_bonus - fines
        lines.append(f"{e('card')} К выплате за смену: {h(format_money(net))}")
    return "\n".join(lines)


def access_denied() -> str:
    return (
        f"{e('prohibited')} У вас нет доступа к этому боту.\n\n"
        f"{e('person')} Попросите управляющего добавить вас в разделе «Команда» и сообщите ему ваш Telegram ID."
    )


def welcome_developer() -> str:
    return (
        f"{e('wave')} Привет! Вы разработчик Palace Adms.\n\n"
        f"{e('tools')} Доступны все функции управляющего и администратора.\n"
        f"{e('person')} Управляющих можно добавлять в разделе «Команда».\n"
        f"{e('phone')} Откройте приложение кнопкой ниже."
    )


def welcome_manager() -> str:
    return (
        f"{e('wave')} Привет! Вы управляющий клуба Palace.\n\n"
        f"{e('phone')} Все функции — в приложении: откройте его кнопкой ниже.\n"
        f"{e('plus')} Админов добавляйте в разделе «Команда»."
    )


def welcome_admin(*, langame_linked: bool, bar_bonus_percent: float, fixed_salary: float) -> str:
    pct = format_percent(bar_bonus_percent)
    text = (
        f"{e('wave')} Привет! Я считаю вашу зарплату.\n\n"
        f"{e('money')} {h(format_money(fixed_salary))} за клубную смену (12 ч)\n"
        f"   работа по часам + {h(format_money(500))} уборка первому админу\n"
        f"{e('burger')} + {h(pct)}% от продаж бара — сразу при продаже\n"
        f"{e('date')} Выплаты: 16-го (за 1–15) и 1-го (за 16–конец месяца)\n\n"
        f"{e('phone')} Всё — в приложении: откройте его кнопкой ниже."
    )
    if not langame_linked:
        text += f"\n\n{e('link')} Привяжите LANGAME — кнопка «Привязать аккаунт»."
    return text


def welcome_guest() -> str:
    return f"{e('wave')} Добро пожаловать в Palace Adms!"


def open_app_hint() -> str:
    return (
        f"{e('phone')} Бот теперь работает как приложение. "
        "Откройте его кнопкой ниже или через кнопку меню рядом с полем ввода."
    )


def webapp_not_configured() -> str:
    return f"{e('warning')} Приложение ещё не настроено: администратор сервера должен указать WEBAPP_URL."


def not_registered() -> str:
    return f"{e('cancel')} Вы не зарегистрированы. Обратитесь к управляющему."


def link_langame_first() -> str:
    return f"{e('link')} Сначала привяжите LANGAME — кнопка «Привязать аккаунт»."


def link_langame_for_salary() -> str:
    return f"{e('link')} Для расчёта зарплаты привяжите LANGAME — кнопка «Привязать аккаунт»."


def settlement_notice(amount: float, when: str) -> str:
    return (
        f"{e('money')} Баланс обнулён\n\n"
        f"{e('money_bag')} Выплата: {h(format_money(amount))}\n"
        f"{e('date')} Дата: {h(when)}\n\n"
        f"{e('party')} Новый баланс: {h(format_money(0))}"
    )


def fine_received(fine_id: int, amount: float, reason: str, *, shift_id: int | None = None) -> str:
    shift_text = f" (смена #{shift_id})" if shift_id else ""
    return (
        f"{e('warning')} Вам выписан штраф #{fine_id}\n"
        f"{e('money')} Сумма: {h(format_money(amount))}{h(shift_text)}\n"
        f"{e('memo')} Причина: {h(reason)}"
    )


def fine_cancelled_notify(fine_id: int, amount: float, reason: str) -> str:
    return (
        f"{e('check')} Штраф #{fine_id} снят\n"
        f"{e('money')} Сумма: {h(format_money(amount))}\n"
        f"{e('memo')} Причина: {h(reason)}"
    )


def admin_added_notify(name: str) -> str:
    return (
        f"{e('party')} Вас добавили в бот Palace Adms как администратора ({h(name)}).\n"
        f"{e('wave')} Нажмите /start, чтобы открыть приложение."
    )


def admin_removed_notify() -> str:
    return f"{e('prohibited')} Вас убрали из бота Palace Adms. Доступ закрыт."


def manager_shift_opened(*, name: str, shift_id: int, started_at: str, cash_start: float = 0) -> str:
    lines = [
        f"{e('check')} Смена открыта",
        "",
        f"{e('person')} Админ: {h(name)}",
        f"{e('gear')} Смена #{shift_id}",
        f"{e('date')} Начало: {h(started_at)}",
    ]
    if cash_start > 0:
        lines.append(f"{e('money')} В кассе: {h(format_money(cash_start))}")
    return "\n".join(lines)


def manager_shift_closed(
    *,
    name: str,
    shift_id: int,
    stopped_at: str,
    cash_in_register: float,
    total_revenue: float,
    nal_revenue: float,
    beznal_revenue: float,
    club_revenue: float,
    bar_revenue: float,
    bar_share_percent: float,
    net_salary: float,
    fixed: float,
    bar_bonus: float,
    fines: float,
    bar_bonus_percent: float,
) -> str:
    pct = format_percent(bar_bonus_percent)
    bar_share = format_percent(bar_share_percent)
    lines = [
        f"{e('red')} Смена закрыта",
        "",
        f"{e('person')} Админ: {h(name)}",
        f"{e('gear')} Смена #{shift_id}",
        f"{e('date')} Конец: {h(stopped_at)}",
        "",
        f"{e('money')} В кассе: {h(format_money(cash_in_register))}",
        f"{e('chart_up')} Общая выручка: {h(format_money(total_revenue))}",
        f"{e('money')} Нал: {h(format_money(nal_revenue))}",
        f"{e('card')} Безнал: {h(format_money(beznal_revenue))}",
        f"{e('phone')} Компы (сессии): {h(format_money(club_revenue))}",
        f"{e('burger')} Бар: {h(format_money(bar_revenue))}",
        f"{e('chart')} Бар от выручки: {h(bar_share)}%",
        "",
        f"{e('money_bag')} ЗП админа за смену: {h(format_money(net_salary))}",
        f"   {e('check')} фикс: {h(format_money(fixed))}",
        f"   {e('burger')} {h(pct)}% с бара: {h(format_money(bar_bonus))}",
    ]
    if fines > 0:
        lines.append(f"   {e('warning')} штрафы: −{h(format_money(fines))}")
    lines.append("")
    lines.append(f"{e('newspaper')} Детализация по товарам — в CSV-файле ниже")
    return "\n".join(lines)
