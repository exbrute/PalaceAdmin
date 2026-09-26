(() => {
  "use strict";

  const tg = window.Telegram && window.Telegram.WebApp;
  const app = document.getElementById("app");
  const toastEl = document.getElementById("toast");

  const state = { me: null };

  // ---------- Utilities ----------

  const moneyFormat = new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: "RUB",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  const money = (value) => moneyFormat.format(Number(value || 0));
  const percent = (value) => `${Number(value || 0).toLocaleString("ru-RU", { maximumFractionDigits: 2 })}%`;

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const [key, value] of Object.entries(attrs)) {
        if (value === null || value === undefined || value === false) continue;
        if (key === "class") node.className = value;
        else if (key === "style") node.style.cssText = value;
        else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
        else if (value === true) node.setAttribute(key, "");
        else node.setAttribute(key, value);
      }
    }
    for (const child of children.flat(Infinity)) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  function render(...nodes) {
    app.replaceChildren(...nodes.flat(Infinity).filter(Boolean));
    window.scrollTo(0, 0);
  }

  let toastTimer = null;
  function toast(message, kind) {
    toastEl.textContent = message;
    toastEl.className = `toast show${kind === "error" ? " error" : ""}`;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toastEl.className = "toast"; }, 2800);
  }

  function haptic(type) {
    try {
      if (!tg || !tg.HapticFeedback) return;
      if (type === "success" || type === "error" || type === "warning") tg.HapticFeedback.notificationOccurred(type);
      else tg.HapticFeedback.impactOccurred(type || "light");
    } catch (_) { /* unsupported client */ }
  }

  function confirmAction(message) {
    return new Promise((resolve) => {
      if (tg && tg.showConfirm && tg.isVersionAtLeast && tg.isVersionAtLeast("6.2")) {
        tg.showConfirm(message, (ok) => resolve(Boolean(ok)));
      } else {
        resolve(window.confirm(message));
      }
    });
  }

  const AVATAR_COLORS = ["#e17076", "#7bc862", "#65aadd", "#a695e7", "#ee7aae", "#6ec9cb", "#faa774"];
  function avatar(name, id) {
    const letter = (String(name || "?").trim()[0] || "?").toUpperCase();
    const color = AVATAR_COLORS[Math.abs(Number(id) || 0) % AVATAR_COLORS.length];
    return el("div", { class: "avatar", style: `background:${color}` }, letter);
  }

  // ---------- API ----------

  class ApiError extends Error {
    constructor(message, status) {
      super(message);
      this.status = status;
    }
  }

  async function api(method, path, body) {
    const options = {
      method,
      headers: { Authorization: `tma ${(tg && tg.initData) || ""}` },
    };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    let response;
    try {
      response = await fetch(path, options);
    } catch (_) {
      throw new ApiError("Нет соединения с сервером", 0);
    }
    let data = null;
    try { data = await response.json(); } catch (_) { data = null; }
    if (!response.ok) {
      throw new ApiError((data && data.error) || `Ошибка сервера (${response.status})`, response.status);
    }
    return data;
  }

  // ---------- Router ----------

  const routes = {};
  let renderToken = 0;

  function parseHash() {
    const raw = location.hash.replace(/^#\/?/, "");
    const [path, query] = raw.split("?");
    const parts = (path || "").split("/").filter(Boolean);
    return { name: parts[0] || "home", args: parts.slice(1), params: new URLSearchParams(query || "") };
  }

  function go(path) {
    haptic("light");
    location.hash = `#/${path}`;
  }

  function back() {
    if (history.length > 1 && parseHash().name !== "home") history.back();
    else location.hash = "#/";
  }

  async function navigate() {
    const route = parseHash();
    const view = routes[route.name] || routes.home;
    const token = ++renderToken;
    if (tg && tg.BackButton) {
      if (route.name === "home") tg.BackButton.hide();
      else tg.BackButton.show();
    }
    try {
      await view(route, () => token === renderToken);
    } catch (error) {
      if (token !== renderToken) return;
      renderError(error);
    }
  }

  function renderError(error) {
    render(
      el("div", { class: "empty" },
        el("div", { class: "big" }, "⚠️"),
        el("div", null, error.message || String(error)),
      ),
      el("div", { class: "actions" },
        el("button", { class: "btn secondary", onclick: () => navigate() }, "Повторить"),
      ),
    );
  }

  function loading(title, blocks = 3) {
    const skeletons = [];
    for (let i = 0; i < blocks; i += 1) skeletons.push(el("div", { class: "skeleton", style: `height:${i === 0 ? 120 : 72}px` }));
    render(title ? el("h1", { class: "page-title" }, title) : null, skeletons);
  }

  async function load(isCurrent, title, fetcher, blocks) {
    loading(title, blocks);
    const data = await fetcher();
    if (!isCurrent()) throw Object.assign(new Error("stale"), { stale: true });
    return data;
  }

  // ---------- Reusable blocks ----------

  const pageTitle = (text) => el("h1", { class: "page-title" }, text);
  const sectionTitle = (text) => el("div", { class: "section-title" }, text);

  function kvRow(title, value, opts = {}) {
    return el("li", { class: `row${opts.total ? " total" : ""}` },
      el("div", { class: "grow" },
        el("div", { class: "title" }, title),
        opts.sub ? el("div", { class: "subtitle" }, opts.sub) : null,
      ),
      el("div", { class: `value mono${opts.neg ? " neg" : ""}${opts.pos ? " pos" : ""}` }, value),
    );
  }

  function kvCard(rows, head) {
    return el("div", { class: "card" }, head || null, el("ul", { class: "list kv" }, rows.filter(Boolean)));
  }

  function cardHead(title, badge) {
    return el("div", { class: "card-head" }, el("div", { class: "title" }, title), badge || null);
  }

  function badge(text, color) {
    return el("span", { class: `badge${color ? ` ${color}` : ""}` }, text);
  }

  function empty(icon, text) {
    return el("div", { class: "card" }, el("div", { class: "empty" }, el("div", { class: "big" }, icon), text));
  }

  function banner(text, kind) {
    return el("div", { class: `banner${kind ? ` ${kind}` : ""}` }, text);
  }

  function earningCard(earning, title) {
    return kvCard([
      kvRow("Период", `${earning.start || "—"} — ${earning.stop || "—"}`),
      kvRow("Продажи бара", `${money(earning.bar_sales)} · ${earning.sales_count} поз.`),
      kvRow(`${percent(earning.bar_percent)} с бара`, money(earning.bar_bonus)),
      kvRow("Фикс за смену", money(earning.fixed_total), { sub: earning.fixed_detail }),
      earning.fines ? kvRow("Штрафы", `−${money(earning.fines)}`, { neg: true }) : null,
      kvRow("К выплате за смену", money(earning.net), { total: true }),
    ], cardHead(title || `Смена #${earning.shift_id}`, badge("закрыта", "gray")));
  }

  function openShiftCard(shift, title, withRevenue) {
    const rows = [
      kvRow("Начало", shift.start || "—"),
      kvRow("Продажи бара", `${money(shift.bar_total)} · ${shift.sales_count} поз.`),
    ];
    if (withRevenue) {
      if (shift.total_revenue && shift.total_revenue > 0) {
        rows.push(
          kvRow("Нал", money(shift.nal)),
          kvRow("Безнал", money(shift.beznal)),
          kvRow("Общая выручка", money(shift.total_revenue)),
          kvRow("Бар от выручки", percent(shift.bar_share_percent)),
        );
      } else {
        rows.push(kvRow("Бар от выручки", "— (выручка пока 0 ₽)"));
      }
    }
    rows.push(
      kvRow(`${percent(shift.bar_percent)} с бара (сразу)`, money(shift.bar_bonus)),
      kvRow("Фикс (ориентир)", money(shift.fixed_total), { sub: shift.fixed_detail ? `${shift.fixed_detail} — после закрытия` : "после закрытия" }),
    );
    if (shift.fines) rows.push(kvRow("Штрафы", `−${money(shift.fines)}`, { neg: true }));
    rows.push(kvRow("Ожидаемая выплата", money(shift.net), { total: true }));
    const card = kvCard(rows, cardHead(title || `Смена #${shift.shift_id}`, badge("● открыта", "green")));
    if (shift.group_size > 1) {
      card.append(el("div", { class: "note" }, `В клубной смене ${shift.group_size} админа(ов) — фикс пересчитается по часам после закрытия.`));
    }
    return card;
  }

  function periodHeader(period) {
    return el("div", { class: "stat-grid" },
      el("div", { class: "stat" }, el("div", { class: "k" }, "Период"), el("div", { class: "v", style: "font-size:15px" }, `${period.date_from} — ${period.date_to}`)),
      el("div", { class: "stat" }, el("div", { class: "k" }, "Выплата"), el("div", { class: "v", style: "font-size:15px" }, period.next_payout)),
    );
  }

  function fineRow(fine, opts = {}) {
    const subtitle = [fine.reason, fine.shift_id ? `смена #${fine.shift_id}` : null, fine.created_at].filter(Boolean).join(" · ");
    const row = el("li", { class: "row" },
      el("div", { class: "grow" },
        el("div", { class: "title" }, opts.showAdmin ? `#${fine.id} · ${fine.admin_name}` : `Штраф #${fine.id}`),
        el("div", { class: "subtitle" }, subtitle),
      ),
      el("div", { class: "value neg mono" }, `−${money(fine.amount)}`),
    );
    if (opts.onCancel) {
      row.append(el("button", { class: "btn danger small", onclick: () => opts.onCancel(fine) }, "Снять"));
    }
    return row;
  }

  async function cancelFine(fine) {
    const ok = await confirmAction(`Снять штраф #${fine.id} (${fine.admin_name}, −${money(fine.amount)})?`);
    if (!ok) return false;
    try {
      const result = await api("DELETE", `/api/fines/${fine.id}`);
      haptic("success");
      toast(result.message);
      return true;
    } catch (error) {
      haptic("error");
      toast(error.message, "error");
      return false;
    }
  }

  function submitButton(label) {
    return el("button", { class: "btn", type: "submit" }, label);
  }

  async function withBusy(button, task) {
    const original = Array.from(button.childNodes);
    button.disabled = true;
    button.replaceChildren(el("span", { class: "spinner" }));
    try {
      return await task();
    } finally {
      button.disabled = false;
      button.replaceChildren(...original);
    }
  }

  function formHandler(form, task) {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = form.querySelector("button[type=submit]");
      try {
        await withBusy(button, task);
      } catch (error) {
        haptic("error");
        toast(error.message, "error");
      }
    });
  }

  async function refreshMe() {
    state.me = await api("GET", "/api/me");
    return state.me;
  }

  // ---------- Views: home ----------

  function tile(icon, label, path, opts = {}) {
    return el("button", {
      class: `tile${opts.wide ? " wide" : ""}${opts.attention ? " attention" : ""}`,
      onclick: () => go(path),
    },
    el("div", { class: "icon" }, icon),
    el("div", null, el("div", { class: "label" }, label), opts.sub ? el("div", { class: "sub" }, opts.sub) : null));
  }

  routes.home = async (_route, isCurrent) => {
    if (!state.me) await load(isCurrent, null, refreshMe, 4);
    else refreshMe().then(() => { if (isCurrent() && parseHash().name === "home") renderHome(); }).catch(() => {});
    renderHome();
  };

  function renderHome() {
    const me = state.me;
    const hero = el("div", { class: "hero" },
      el("div", { class: "hello" }, "Palace Adms"),
      el("div", { class: "name" }, me.name),
      el("span", { class: "role" }, me.role_label),
    );
    if (me.balance) {
      hero.append(
        el("div", { class: "amount-label" }, "Баланс в боте"),
        el("div", { class: "amount mono" }, money(me.balance.balance)),
        el("div", { class: "meta" },
          el("span", null, `Смен: ${me.balance.shifts_count}`),
          el("span", null, `С бара: ${percent(me.bar_percent)}`),
        ),
      );
    } else if (me.is_manager) {
      hero.append(el("div", { class: "meta" }, el("span", null, `Процент с бара: ${percent(me.bar_percent)}`)));
    }

    const nodes = [hero];
    if (me.needs_link && !me.is_manager) {
      nodes.push(el("div", { class: "tiles", style: "margin-bottom:10px" },
        tile("🔗", "Привязать аккаунт LANGAME", "link", { wide: true, attention: true, sub: "Без привязки смены не считаются" })));
    }

    if (me.is_manager) {
      nodes.push(
        sectionTitle("Смены"),
        el("div", { class: "tiles" },
          tile("💰", "Текущая смена", "shift", { sub: "Кто на смене сейчас" }),
          tile("📄", "Отчёт смены", "shift-report", { sub: "По id смены" }),
        ),
        sectionTitle("Команда"),
        el("div", { class: "tiles" },
          tile("👥", "Команда", "team", { sub: "Админы и управляющие" }),
          tile("➕", "Добавить админа", "add-admin"),
          me.is_developer ? tile("🛠", "Добавить управляющего", "add-manager", { wide: true }) : null,
        ),
        sectionTitle("Деньги"),
        el("div", { class: "tiles" },
          tile("📊", "Ведомость", "payroll", { sub: "За полмесяца + CSV" }),
          tile("📈", "Рейтинг бара", "leaderboard"),
          tile("🍹", "% бара", "bar-percent", { sub: percent(me.bar_percent) }),
          tile("📢", "Рассылка", "broadcast", { sub: "Всем админам" }),
        ),
        sectionTitle("Штрафы"),
        el("div", { class: "tiles" },
          tile("➖", "Выписать штраф", "fine-new"),
          tile("📋", "Все штрафы", "fines", { sub: "Снять штраф" }),
        ),
        sectionTitle("Прочее"),
        el("div", { class: "tiles" },
          tile("👤", "Профиль", "profile"),
          tile("❓", "Помощь", "help"),
          me.needs_link ? tile("🔗", "Привязать аккаунт", "link", { wide: true, sub: "Если вы тоже работаете сменами" }) : null,
        ),
      );
    } else {
      nodes.push(el("div", { class: "tiles" },
        tile("💰", "Текущая смена", "shift", { sub: "Открытая или последняя" }),
        tile("📅", "За полмесяца", "half", { sub: "Зарплата за период" }),
        tile("⚠️", "Мои штрафы", "myfines"),
        tile("👤", "Профиль", "profile"),
        tile("❓", "Помощь", "help", { wide: true }),
      ));
    }
    render(nodes);
  }

  // ---------- Views: administrator ----------

  routes.shift = async (_route, isCurrent) => {
    const data = await load(isCurrent, "Текущая смена", () => api("GET", "/api/shift/current"));
    const nodes = [pageTitle("Текущая смена")];
    if (data.mode === "manager") {
      if (!data.shifts.length) nodes.push(empty("😴", "Сейчас ни один администратор не на смене."));
      for (const item of data.shifts) {
        nodes.push(openShiftCard(item.shift, `${item.admin.name} · #${item.shift.shift_id}`, true));
      }
    } else if (data.mode === "open") {
      nodes.push(openShiftCard(data.shift, `Смена #${data.shift.shift_id}`, false));
    } else if (data.mode === "closed") {
      nodes.push(banner("Сейчас смена не открыта. Последняя закрытая смена:", "info"));
      nodes.push(earningCard(data.earning));
    } else {
      nodes.push(empty("📋", "Нет открытой смены, и закрытых смен пока нет. После смены в LANGAME загляните снова."));
    }
    nodes.push(el("div", { class: "actions" }, el("button", { class: "btn secondary", onclick: () => navigate() }, "Обновить")));
    render(nodes);
  };

  routes.half = async (_route, isCurrent) => {
    const data = await load(isCurrent, "За полмесяца", () => api("GET", "/api/half-month"));
    const { period, summary, balance } = data;
    const nodes = [pageTitle(`Зарплата за ${period.label}`), periodHeader(period)];
    nodes.push(kvCard([
      kvRow("Смен", String(summary.shifts)),
      kvRow("Продажи бара", money(summary.bar_sales)),
      kvRow(`${percent(summary.bar_percent)} с бара`, money(summary.bar_bonus)),
      kvRow("Фикс", money(summary.fixed)),
      kvRow("Начислено", money(summary.gross)),
      summary.fines ? kvRow("Штрафы", `−${money(summary.fines)}`, { neg: true }) : null,
      kvRow("Итого за период", money(summary.net), { total: true }),
    ], cardHead("Итоги периода")));

    nodes.push(kvCard([
      kvRow("С бара сразу", money(balance.bar_bonus_instant)),
      kvRow(`За смены (${balance.shifts_count})`, money(balance.shift_earned)),
      kvRow("Штрафы", `−${money(balance.fines_total)}`, { neg: balance.fines_total > 0 }),
      kvRow("Выплачено", money(balance.settled_total)),
      kvRow("Баланс в боте", money(balance.balance), { total: true }),
    ], cardHead("Баланс")));

    if (summary.earnings.length) {
      nodes.push(sectionTitle("Смены за период"));
      for (const earning of summary.earnings) nodes.push(earningCard(earning));
    }
    render(nodes);
  };

  routes.myfines = async (_route, isCurrent) => {
    const data = await load(isCurrent, "Мои штрафы", () => api("GET", "/api/my/fines"));
    const nodes = [pageTitle("Мои штрафы")];
    if (!data.fines.length) nodes.push(empty("👍", "Штрафов нет — так держать!"));
    else nodes.push(el("div", { class: "card" }, el("ul", { class: "list" }, data.fines.map((fine) => fineRow(fine)))));
    render(nodes);
  };

  routes.profile = async (_route, isCurrent) => {
    const me = await load(isCurrent, "Профиль", refreshMe, 2);
    const rows = [
      kvRow("Роль", me.role_label),
      kvRow("Имя", me.name),
      kvRow("Telegram ID", String(me.telegram_id)),
    ];
    if (me.balance || me.langame_user_id || me.needs_link) {
      rows.push(kvRow("LANGAME", me.langame_user_id ? `id ${me.langame_user_id}` : "не привязан"));
      rows.push(kvRow("Email", me.email || "—"));
    }
    const nodes = [pageTitle("Профиль"), kvCard(rows)];
    if (me.balance) {
      nodes.push(kvCard([
        kvRow("Баланс в боте", money(me.balance.balance), { total: true }),
        kvRow("Смен", String(me.balance.shifts_count)),
        kvRow("Начислено", money(me.balance.gross_earned)),
        kvRow("Штрафы", `−${money(me.balance.fines_total)}`, { neg: me.balance.fines_total > 0 }),
        kvRow("Выплачено", money(me.balance.settled_total)),
      ]));
    }
    if (me.needs_link) {
      nodes.push(el("div", { class: "actions" }, el("button", { class: "btn", onclick: () => go("link") }, "🔗 Привязать аккаунт LANGAME")));
    } else if (me.langame_user_id) {
      nodes.push(el("div", { class: "actions" }, el("button", { class: "btn secondary", onclick: () => go("link") }, "Перепривязать LANGAME")));
    }
    render(nodes);
  };

  routes.link = async () => {
    const input = el("input", { name: "query", required: true, autocomplete: "email", placeholder: "admin@example.com или 123" });
    const form = el("form", null,
      el("div", { class: "card" },
        el("div", { class: "field" },
          el("label", null, "Email или id администратора в LANGAME"),
          input,
          el("div", { class: "help" }, "После привязки бот начнёт считать ваши смены и продажи бара."),
        ),
      ),
      el("div", { class: "actions" }, submitButton("Привязать")),
    );
    formHandler(form, async () => {
      const result = await api("POST", "/api/link", { query: input.value });
      state.me = result.me;
      haptic("success");
      toast(result.sync_error ? `${result.message}. ${result.sync_error}` : result.message);
      location.hash = "#/";
    });
    render(pageTitle("Привязка LANGAME"), form);
    input.focus();
  };

  // ---------- Views: manager — team ----------

  routes.team = async (_route, isCurrent) => {
    const data = await load(isCurrent, "Команда", () => api("GET", "/api/team"));
    const me = state.me || {};
    const nodes = [pageTitle("Команда")];

    nodes.push(el("div", { class: "actions two", style: "margin-top:0" },
      el("button", { class: "btn", onclick: () => go("add-admin") }, "➕ Админ"),
      me.is_developer
        ? el("button", { class: "btn secondary", onclick: () => go("add-manager") }, "➕ Управляющий")
        : el("button", { class: "btn secondary", onclick: () => go("fines") }, "📋 Штрафы"),
    ));

    nodes.push(sectionTitle(`Администраторы · ${data.admins.length}`));
    if (!data.admins.length) {
      nodes.push(empty("👤", "Администраторов пока нет. Добавьте первого."));
    } else {
      nodes.push(el("div", { class: "card" }, el("ul", { class: "list" }, data.admins.map((admin) =>
        el("li", { class: "row clickable", onclick: () => go(`admin/${admin.telegram_id}`) },
          avatar(admin.name, admin.telegram_id),
          el("div", { class: "grow" },
            el("div", { class: "title" }, admin.name),
            el("div", { class: "subtitle" }, admin.langame_user_id ? `LANGAME id ${admin.langame_user_id}` : "LANGAME не привязан"),
          ),
          el("div", { class: "value mono" }, money(admin.balance)),
          el("div", { class: "chev" }, "›"),
        )))));
    }

    nodes.push(sectionTitle("Управляющие"));
    if (!data.managers.length) {
      nodes.push(empty("👤", "Управляющих пока нет."));
    } else {
      nodes.push(el("div", { class: "card" }, el("ul", { class: "list" }, data.managers.map((manager) => {
        const row = el("li", { class: "row" },
          avatar(manager.name, manager.telegram_id),
          el("div", { class: "grow" },
            el("div", { class: "title" }, manager.name),
            el("div", { class: "subtitle" }, `TG ${manager.telegram_id}`),
          ),
        );
        if (me.is_developer && manager.removable) {
          row.append(el("button", {
            class: "btn danger small",
            onclick: async () => {
              if (!(await confirmAction(`Снять управляющего ${manager.name}?`))) return;
              try {
                const result = await api("DELETE", `/api/managers/${manager.telegram_id}`);
                haptic("success");
                toast(result.message);
                navigate();
              } catch (error) {
                haptic("error");
                toast(error.message, "error");
              }
            },
          }, "Снять"));
        }
        return row;
      }))));
    }

    if (data.developers.length) {
      nodes.push(sectionTitle("Разработчики"));
      nodes.push(el("div", { class: "card" }, el("ul", { class: "list" }, data.developers.map((id) =>
        el("li", { class: "row" }, avatar("🛠", id), el("div", { class: "grow title" }, `TG ${id}`))))));
    }
    render(nodes);
  };

  routes.admin = async (route, isCurrent) => {
    const id = route.args[0];
    const card = await load(isCurrent, "Карточка", () => api("GET", `/api/admins/${id}`));
    const nodes = [pageTitle(card.name)];
    if (card.sync_error) nodes.push(banner(card.sync_error, "error"));

    nodes.push(kvCard([
      kvRow("Роль", card.role_label),
      kvRow("Telegram ID", String(card.telegram_id)),
      kvRow("LANGAME", card.langame_user_id ? `id ${card.langame_user_id}` : "не привязан"),
      card.email ? kvRow("Email", card.email) : null,
      kvRow("Баланс в боте", money(card.balance.balance), { total: true }),
    ]));

    if (card.langame_user_id) {
      const s = card.summary;
      nodes.push(kvCard([
        kvRow("Смен", String(s.shifts)),
        kvRow("Продажи бара", money(s.bar_sales)),
        kvRow("Начислено", money(s.gross)),
        s.fines ? kvRow("Штрафы", `−${money(s.fines)}`, { neg: true }) : null,
        kvRow("Итого за полмесяца", money(s.net), { total: true }),
      ], cardHead(`За ${card.period.label}`)));
      if (card.last_earning) nodes.push(earningCard(card.last_earning, `Последняя смена #${card.last_earning.shift_id}`));
    } else {
      nodes.push(banner("LANGAME не привязан — новые смены не синхронизируются. Администратор может привязать аккаунт в приложении."));
    }

    nodes.push(el("div", { class: "actions two" },
      el("button", { class: "btn", onclick: () => go(`fine-new?admin=${card.telegram_id}`) }, "➖ Штраф"),
      el("button", { class: "btn secondary", onclick: () => go(`fines?admin=${card.telegram_id}`) }, "📋 Штрафы"),
    ));

    if (card.fines.length) {
      nodes.push(sectionTitle("Последние штрафы"));
      nodes.push(el("div", { class: "card" }, el("ul", { class: "list" }, card.fines.map((fine) =>
        fineRow(fine, { onCancel: async (f) => { if (await cancelFine(f)) navigate(); } })))));
    }

    nodes.push(el("div", { class: "actions" }, el("button", {
      class: "btn danger",
      onclick: async () => {
        if (!(await confirmAction(`Убрать ${card.name} из бота? Доступ будет закрыт.`))) return;
        try {
          const result = await api("DELETE", `/api/admins/${card.telegram_id}`);
          haptic("success");
          toast(result.message);
          history.back();
        } catch (error) {
          haptic("error");
          toast(error.message, "error");
        }
      },
    }, "🚫 Убрать из бота")));
    render(nodes);
  };

  function personForm({ title, nameLabel, submitLabel, endpoint }) {
    const nameInput = el("input", { name: "name", required: true, minlength: "2", placeholder: "Иван" });
    const idInput = el("input", { name: "telegram_id", required: true, inputmode: "numeric", pattern: "[0-9]*", placeholder: "123456789" });
    const form = el("form", null,
      el("div", { class: "card" },
        el("div", { class: "field" }, el("label", null, nameLabel), nameInput),
        el("div", { class: "field" },
          el("label", null, "Telegram ID"),
          idInput,
          el("div", { class: "help" }, "Человек может узнать свой ID, написав боту /start — бот покажет его."),
        ),
      ),
      el("div", { class: "actions" }, submitButton(submitLabel)),
    );
    formHandler(form, async () => {
      const result = await api("POST", endpoint, { name: nameInput.value, telegram_id: idInput.value });
      haptic("success");
      toast(result.notified === false ? `${result.message}. Уведомление не доставлено — пусть напишет боту /start.` : result.message);
      location.hash = "#/team";
    });
    render(pageTitle(title), form);
    nameInput.focus();
  }

  routes["add-admin"] = async () => personForm({
    title: "Новый администратор",
    nameLabel: "Имя администратора",
    submitLabel: "Добавить администратора",
    endpoint: "/api/admins",
  });

  routes["add-manager"] = async () => personForm({
    title: "Новый управляющий",
    nameLabel: "Имя управляющего",
    submitLabel: "Добавить управляющего",
    endpoint: "/api/managers",
  });

  // ---------- Views: manager — money ----------

  routes.payroll = async (_route, isCurrent) => {
    const data = await load(isCurrent, "Ведомость", () => api("GET", "/api/payroll"));
    const nodes = [pageTitle(`Ведомость за ${data.period.label}`), periodHeader(data.period)];
    if (!data.rows.length) {
      nodes.push(empty("📊", "Нет админов с привязанным LANGAME."));
    } else {
      nodes.push(el("div", { class: "card" }, el("ul", { class: "list" }, data.rows.map((row) =>
        el("li", { class: "row clickable", onclick: () => go(`admin/${row.telegram_id}`) },
          avatar(row.name, row.telegram_id),
          el("div", { class: "grow" },
            el("div", { class: "title" }, row.name),
            el("div", { class: "subtitle" }, `${row.shifts} смен · баланс ${money(row.balance)}${row.fines ? ` · штрафы −${money(row.fines)}` : ""}`),
          ),
          el("div", { class: "value mono" }, money(row.net)),
        )))));
      nodes.push(kvCard([kvRow("Итого за полмесяца", money(data.total), { total: true })]));
    }
    const exportButton = el("button", { class: "btn secondary" }, "📰 Экспорт CSV в чат");
    exportButton.addEventListener("click", () => withBusy(exportButton, async () => {
      try {
        const result = await api("POST", "/api/payroll/export");
        haptic("success");
        toast(result.message);
      } catch (error) {
        haptic("error");
        toast(error.message, "error");
      }
    }));
    nodes.push(el("div", { class: "actions" }, exportButton));
    render(nodes);
  };

  routes.leaderboard = async (_route, isCurrent) => {
    const data = await load(isCurrent, "Рейтинг бара", () => api("GET", "/api/leaderboard"));
    const nodes = [pageTitle(`Рейтинг бара · ${data.period.label}`)];
    if (!data.rows.length) {
      nodes.push(empty("🍹", "За полмесяца продаж бара пока нет."));
    } else {
      const medals = ["🥇", "🥈", "🥉"];
      nodes.push(el("div", { class: "card" }, el("ul", { class: "list" }, data.rows.map((row, index) =>
        el("li", { class: "row" },
          el("div", { class: "rank" }, medals[index] || String(index + 1)),
          el("div", { class: "grow" },
            el("div", { class: "title" }, row.name),
            el("div", { class: "subtitle" }, `${row.shifts} смен`),
          ),
          el("div", { class: "value mono" }, money(row.bar_sales)),
        )))));
    }
    render(nodes);
  };

  routes["bar-percent"] = async (_route, isCurrent) => {
    const data = await load(isCurrent, "Процент с бара", () => api("GET", "/api/settings/bar-percent"), 1);
    const input = el("input", { name: "value", required: true, inputmode: "decimal", value: String(data.value) });
    const form = el("form", null,
      el("div", { class: "card" },
        el("div", { class: "field" },
          el("label", null, "Процент с продаж бара (0–100)"),
          input,
          el("div", { class: "help" }, "Новые продажи начисляются по этому проценту. Уже начисленные суммы не пересчитываются."),
        ),
      ),
      el("div", { class: "actions" }, submitButton("Сохранить")),
    );
    formHandler(form, async () => {
      const result = await api("PUT", "/api/settings/bar-percent", { value: input.value });
      if (state.me) state.me.bar_percent = result.value;
      haptic("success");
      toast(`${result.message}: ${percent(result.value)}`);
      history.back();
    });
    render(pageTitle("Процент с бара"), form);
  };

  routes.broadcast = async () => {
    const textarea = el("textarea", { name: "text", required: true, placeholder: "Текст сообщения для всех администраторов" });
    const form = el("form", null,
      el("div", { class: "card" }, el("div", { class: "field" }, el("label", null, "Сообщение"), textarea)),
      el("div", { class: "actions" }, submitButton("📢 Отправить всем")),
    );
    formHandler(form, async () => {
      if (!(await confirmAction("Отправить сообщение всем администраторам?"))) return;
      const result = await api("POST", "/api/broadcast", { text: textarea.value });
      haptic("success");
      toast(result.message);
      history.back();
    });
    render(pageTitle("Рассылка"), form);
    textarea.focus();
  };

  // ---------- Views: manager — fines ----------

  routes["fine-new"] = async (route, isCurrent) => {
    const team = await load(isCurrent, "Штраф", () => api("GET", "/api/team"), 2);
    if (!team.admins.length) {
      render(pageTitle("Штраф"), empty("👤", "В боте пока нет администраторов."));
      return;
    }
    const preselected = route.params.get("admin");
    const select = el("select", { name: "telegram_id", required: true },
      el("option", { value: "", disabled: true, selected: !preselected }, "Выберите администратора"),
      team.admins.map((admin) => el("option", {
        value: String(admin.telegram_id),
        selected: String(admin.telegram_id) === preselected,
      }, admin.name)),
    );
    const amount = el("input", { name: "amount", required: true, inputmode: "decimal", placeholder: "500" });
    const reason = el("textarea", { name: "reason", required: true, placeholder: "Опоздание на смену", style: "min-height:72px" });
    const shift = el("input", { name: "shift_id", inputmode: "numeric", pattern: "[0-9]*", placeholder: "необязательно" });
    const form = el("form", null,
      el("div", { class: "card" },
        el("div", { class: "field" }, el("label", null, "Кому"), select),
        el("div", { class: "field" }, el("label", null, "Сумма, ₽"), amount),
        el("div", { class: "field" }, el("label", null, "Причина"), reason),
        el("div", { class: "field" }, el("label", null, "Id смены"), shift),
      ),
      el("div", { class: "actions" }, submitButton("Выписать штраф")),
    );
    formHandler(form, async () => {
      const result = await api("POST", "/api/fines", {
        telegram_id: select.value,
        amount: amount.value,
        reason: reason.value,
        shift_id: shift.value || null,
      });
      haptic("success");
      toast(result.message);
      history.back();
    });
    render(pageTitle("Выписать штраф"), form);
  };

  routes.fines = async (route, isCurrent) => {
    const adminId = route.params.get("admin") || "";
    const [finesData, team] = await load(isCurrent, "Штрафы", () => Promise.all([
      api("GET", `/api/fines${adminId ? `?telegram_id=${encodeURIComponent(adminId)}` : ""}`),
      api("GET", "/api/team"),
    ]));

    const filter = el("div", { class: "segmented" },
      el("button", { class: adminId ? "" : "active", onclick: () => { location.replace("#/fines"); } }, "Все"),
      team.admins.map((admin) => el("button", {
        class: String(admin.telegram_id) === adminId ? "active" : "",
        onclick: () => { location.replace(`#/fines?admin=${admin.telegram_id}`); },
      }, admin.name)),
    );

    const nodes = [pageTitle("Штрафы"), team.admins.length ? filter : null];
    nodes.push(el("div", { class: "actions", style: "margin-top:0" },
      el("button", { class: "btn", onclick: () => go(`fine-new${adminId ? `?admin=${adminId}` : ""}`) }, "➖ Выписать штраф")));
    if (!finesData.fines.length) {
      nodes.push(empty("👍", "Активных штрафов нет."));
    } else {
      nodes.push(el("div", { class: "card" }, el("ul", { class: "list" }, finesData.fines.map((fine) =>
        fineRow(fine, { showAdmin: true, onCancel: async (f) => { if (await cancelFine(f)) navigate(); } })))));
    }
    render(nodes);
  };

  // ---------- Views: manager — shift report ----------

  routes["shift-report"] = async (route) => {
    const input = el("input", { name: "shift_id", required: true, inputmode: "numeric", pattern: "[0-9]*", placeholder: "12345", value: route.params.get("id") || "" });
    const result = el("div");
    const form = el("form", null,
      el("div", { class: "card" }, el("div", { class: "field" }, el("label", null, "Id смены в LANGAME"), input)),
      el("div", { class: "actions" }, submitButton("Показать отчёт")),
    );
    formHandler(form, async () => {
      const data = await api("GET", `/api/shifts/${encodeURIComponent(input.value.trim())}/report`);
      haptic("success");
      const title = `${data.admin.name} · #${data.open ? data.shift.shift_id : data.earning.shift_id}`;
      result.replaceChildren(data.open ? openShiftCard(data.shift, title, true) : earningCard(data.earning, title));
      history.replaceState(null, "", `#/shift-report?id=${encodeURIComponent(input.value.trim())}`);
    });
    render(pageTitle("Отчёт смены"), form, result);
    if (input.value) form.requestSubmit();
    else input.focus();
  };

  // ---------- Views: help ----------

  routes.help = async () => {
    const me = state.me || {};
    const blocks = [
      el("p", null, "Palace Adms считает зарплату администраторов клуба по данным LANGAME."),
      el("ul", null,
        el("li", null, `Фикс ${money(me.fixed_salary)} за клубную смену (12 ч): работа по часам + ${money(me.fixed_cleaning)} за уборку первому админу.`),
        el("li", null, `${percent(me.bar_percent)} от продаж бара — начисляется сразу при продаже.`),
        el("li", null, "Выплаты: 16-го (за 1–15) и 1-го (за 16 – конец месяца). В день выплаты баланс обнуляется."),
      ),
    ];
    if (me.is_manager) {
      blocks.push(
        el("p", null, el("b", null, "Управляющему:")),
        el("ul", null,
          el("li", null, "Текущая смена — кто из админов на смене, выручка и доля бара."),
          el("li", null, "Команда — добавить или убрать админа, карточка админа."),
          el("li", null, "Ведомость — итоги за полмесяца и экспорт CSV в чат."),
          el("li", null, "Штрафы — выписать и снять; админ получает уведомление в чате."),
          el("li", null, "Рассылка — сообщение всем админам в чат бота."),
        ),
      );
    } else {
      blocks.push(el("ul", null,
        el("li", null, "Текущая смена — открытая или последняя закрытая."),
        el("li", null, "За полмесяца — начисления с 1 по 15 или с 16 по конец месяца."),
      ));
    }
    blocks.push(el("p", { class: "muted" }, "Уведомления о продажах, закрытии смен, штрафах и выплатах приходят в чат с ботом."));
    render(pageTitle("Помощь"), el("div", { class: "card pad help-text" }, blocks));
  };

  // ---------- Boot ----------

  function renderNoAccess(me) {
    const copy = el("button", {
      class: "btn secondary",
      onclick: async () => {
        try {
          await navigator.clipboard.writeText(String(me.telegram_id));
          toast("Telegram ID скопирован");
        } catch (_) {
          toast(String(me.telegram_id));
        }
      },
    }, `Скопировать ID ${me.telegram_id}`);
    render(
      el("div", { class: "empty" },
        el("div", { class: "big" }, "🔒"),
        el("div", null, me.message),
      ),
      el("div", { class: "actions" }, copy),
    );
  }

  async function boot() {
    if (tg) {
      tg.ready();
      tg.expand();
      try {
        tg.setHeaderColor("secondary_bg_color");
        tg.setBackgroundColor("secondary_bg_color");
      } catch (_) { /* older clients */ }
      if (tg.BackButton) tg.BackButton.onClick(back);
    }

    if (!tg || !tg.initData) {
      render(el("div", { class: "empty" },
        el("div", { class: "big" }, "📱"),
        el("div", null, "Откройте приложение из Telegram-бота Palace Adms."),
      ));
      return;
    }

    try {
      await refreshMe();
    } catch (error) {
      renderError(error);
      return;
    }
    if (!state.me.access) {
      renderNoAccess(state.me);
      return;
    }
    window.addEventListener("hashchange", navigate);
    navigate();
  }

  window.addEventListener("unhandledrejection", (event) => {
    if (event.reason && event.reason.stale) event.preventDefault();
  });

  boot();
})();
