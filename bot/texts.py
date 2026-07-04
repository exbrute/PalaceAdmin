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
        f"{e('person')} Попросите управляющего добавить вас через «Добавить админа»."
    )


def welcome_developer() -> str:
    return (
        f"{e('wave')} Привет! Вы разработчик Palace Adms.\n\n"
        f"{e('tools')} Доступны все функции управляющего и администратора.\n"
        f"{e('person')} Можете добавлять управляющих через «Добавить управляющего»."
    )


def welcome_manager() -> str:
    return (
        f"{e('wave')} Привет! Вы управляющий клуба Palace.\n\n"
        f"{e('folder')} Используйте кнопки меню ниже.\n"
        f"{e('plus')} Добавляйте админов через «Добавить админа»."
    )


def welcome_admin(*, langame_linked: bool, bar_bonus_percent: float, fixed_salary: float) -> str:
    pct = format_percent(bar_bonus_percent)
    text = (
        f"{e('wave')} Привет! Я считаю вашу зарплату.\n\n"
        f"{e('money')} {h(format_money(fixed_salary))} за клубную смену (12 ч)\n"
        f"   работа по часам + {h(format_money(500))} уборка первому админу\n"
        f"{e('burger')} + {h(pct)}% от продаж бара — сразу при продаже\n"
        f"{e('date')} Выплаты: 16-го (за 1–15) и 1-го (за 16–конец месяца)\n\n"
        f"{e('phone')} Выберите действие в меню."
    )
    if not langame_linked:
        text += f"\n\n{e('link')} Привяжите LANGAME — кнопка «Привязать аккаунт»."
    return text


def welcome_guest() -> str:
    return f"{e('wave')} Добро пожаловать в Palace Adms!"


def help_header(*, bar_bonus_percent: float, fixed_salary: float) -> str:
    pct = format_percent(bar_bonus_percent)
    return (
        f"{e('book')} Palace Adms — зарплата администраторов\n"
        f"{e('money')} {h(format_money(fixed_salary))} за клубную смену (12 ч) + {e('burger')} {h(pct)}% от бара\n"
        f"   работа по часам, уборка {h(format_money(500))} — первому админу\n"
        f"{e('date')} Выплаты: 16-го (1–15) и 1-го (16–конец месяца)"
    )


def help_admin_section() -> list[str]:
    return [
        "",
        f"{e('person')} Администратор:",
        f"• {e('money_bag')} Текущая смена — открытая или последняя закрытая",
        f"• {e('date')} За полмесяца — с 1 по 15 или с 16 по конец месяца",
        f"• {e('warning')} Мои штрафы",
    ]


def help_manager_section() -> list[str]:
    return [
        "",
        f"{e('person')} Управляющий:",
        f"• {e('money_bag')} Текущая смена — кто из админов сейчас на смене",
        f"• {e('plus')} Добавить / {e('trash')} убрать админа",
        f"• {e('people')} Команда, {e('chart')} ведомость, {e('newspaper')} экспорт CSV",
        f"• {e('chart_up')} рейтинг бара",
        f"• {e('warning')} Штраф / {e('trash')} убрать штраф",
        f"• {e('magnifier')} Карточка админа, {e('page')} отчёт смены",
        f"• {e('megaphone')} Рассылка всем админам",
        f"• {e('burger')} % бара — настройка процента с продаж",
    ]


def help_developer_section() -> list[str]:
    return [
        "",
        f"{e('tools')} Разработчик:",
        f"• {e('person')} Добавить управляющего — по имени и Telegram ID",
    ]


def no_fines() -> str:
    return f"{e('check')} Штрафов нет — так держать! {e('thumbs_up')}"


def action_cancelled() -> str:
    return f"{e('cancel')} Действие отменено."


def manager_only_fines() -> str:
    return f"{e('lock')} Штрафы может выдавать только управляющий."


def manager_only() -> str:
    return f"{e('lock')} Команда доступна только управляющему."


def developer_only() -> str:
    return f"{e('lock')} Команда доступна только разработчику."


def not_registered() -> str:
    return f"{e('cancel')} Вы не зарегистрированы. Обратитесь к управляющему."


def link_langame_first() -> str:
    return f"{e('link')} Сначала привяжите LANGAME — кнопка «Привязать аккаунт»."


def link_langame_for_salary() -> str:
    return f"{e('link')} Для расчёта зарплаты привяжите LANGAME — кнопка «Привязать аккаунт»."


def no_shifts_yet() -> str:
    return (
        f"{e('folder')} Нет открытой смены и закрытых смен пока нет. "
        "После смены в LANGAME нажмите снова."
    )


def no_open_admin_shift() -> str:
    return f"{e('folder')} Сейчас ни один администратор не на смене."


def settlement_notice(amount: float, when: str) -> str:
    return (
        f"{e('money')} Баланс обнулён\n\n"
        f"{e('money_bag')} Выплата: {h(format_money(amount))}\n"
        f"{e('date')} Дата: {h(when)}\n\n"
        f"{e('party')} Новый баланс: {h(format_money(0))}"
    )


def fine_issued(fine_id: int, name: str, amount: float, reason: str, *, shift_id: int | None = None) -> str:
    shift_text = f" (смена #{shift_id})" if shift_id else ""
    return (
        f"{e('warning')} Штраф #{fine_id} выписан\n"
        f"{e('person')} Кому: {h(name)}\n"
        f"{e('money')} Сумма: {h(format_money(amount))}{h(shift_text)}\n"
        f"{e('memo')} Причина: {h(reason)}"
    )


def fine_received(fine_id: int, amount: float, reason: str, *, shift_id: int | None = None) -> str:
    shift_text = f" (смена #{shift_id})" if shift_id else ""
    return (
        f"{e('warning')} Вам выписан штраф #{fine_id}\n"
        f"{e('money')} Сумма: {h(format_money(amount))}{h(shift_text)}\n"
        f"{e('memo')} Причина: {h(reason)}"
    )


def fine_cancelled(fine_id: int, name: str, amount: float, reason: str) -> str:
    return (
        f"{e('check')} Штраф #{fine_id} снят\n"
        f"{e('person')} Кому: {h(name)}\n"
        f"{e('money')} Сумма: {h(format_money(amount))}\n"
        f"{e('memo')} Причина: {h(reason)}"
    )


def fine_cancelled_notify(fine_id: int, amount: float, reason: str) -> str:
    return (
        f"{e('check')} Штраф #{fine_id} снят\n"
        f"{e('money')} Сумма: {h(format_money(amount))}\n"
        f"{e('memo')} Причина: {h(reason)}"
    )


def admin_added(name: str, telegram_id: int) -> str:
    return (
        f"{e('check')} Администратор добавлен:\n"
        f"{e('person')} {h(name)}\n"
        f"{e('info')} Telegram ID: {h(telegram_id)}"
    )


def admin_added_notify(name: str) -> str:
    return (
        f"{e('party')} Вас добавили в бот Palace Adms как администратора ({h(name)}).\n"
        f"{e('wave')} Нажмите /start для входа."
    )


def admin_removed(name: str, telegram_id: int) -> str:
    return (
        f"{e('prohibited')} Администратор убран из бота:\n"
        f"{e('person')} {h(name)}\n"
        f"{e('info')} Telegram ID: {h(telegram_id)}"
    )


def admin_removed_notify() -> str:
    return f"{e('prohibited')} Вас убрали из бота Palace Adms. Доступ закрыт."


def langame_linked(name: str, user_id: int, *, synced: int = 0, sync_error: str | None = None) -> str:
    extra = f"\n{e('refresh')} Синхронизировано смен: {synced}" if synced else ""
    if sync_error and synced == 0:
        extra = f"\n{e('warning')} {h(sync_error)}"
    return (
        f"{e('link')} LANGAME привязан: {h(name)} (id: {user_id}){extra}\n"
        f"{e('money_bag')} Начисления теперь копятся в балансе бота."
    )


def unknown_command() -> str:
    return (
        f"{e('help')} Не удалось распознать команду. "
        f"Нажмите {e('home')} Меню или выберите кнопку ниже."
    )


def remove_fine_prompt(lines: list[str]) -> str:
    return "\n".join(lines)


def remove_admin_prompt(lines: list[str]) -> str:
    return "\n".join(lines)


def admin_not_found() -> str:
    return f"{e('cancel')} Администратор не найден в боте."


def fine_not_found() -> str:
    return f"{e('cancel')} Штраф не найден."


def fine_already_cancelled() -> str:
    return f"{e('warning')} Штраф уже отменён."


def cannot_remove_developer() -> str:
    return f"{e('prohibited')} Нельзя убрать разработчика."


def cannot_remove_manager() -> str:
    return f"{e('prohibited')} Нельзя убрать управляющего. Используйте /demote."


def remove_admin_failed() -> str:
    return f"{e('cancel')} Не удалось убрать администратора."


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
    club_revenue: float,
    bar_revenue: float,
    net_salary: float,
    fixed: float,
    bar_bonus: float,
    fines: float,
    bar_bonus_percent: float,
) -> str:
    pct = format_percent(bar_bonus_percent)
    lines = [
        f"{e('red')} Смена закрыта",
        "",
        f"{e('person')} Админ: {h(name)}",
        f"{e('gear')} Смена #{shift_id}",
        f"{e('date')} Конец: {h(stopped_at)}",
        "",
        f"{e('money')} В кассе: {h(format_money(cash_in_register))}",
        f"{e('chart_up')} Общая выручка за смену: {h(format_money(total_revenue))}",
        f"{e('phone')} Сессии и услуги: {h(format_money(club_revenue))}",
        f"{e('burger')} Бар: {h(format_money(bar_revenue))}",
        "",
        f"{e('money_bag')} ЗП админа за смену: {h(format_money(net_salary))}",
        f"   {e('check')} фикс: {h(format_money(fixed))}",
        f"   {e('burger')} {h(pct)}% с бара: {h(format_money(bar_bonus))}",
    ]
    if fines > 0:
        lines.append(f"   {e('warning')} штрафы: −{h(format_money(fines))}")
    return "\n".join(lines)
