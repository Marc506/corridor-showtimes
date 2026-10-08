/* Corridor Showtimes, phone pages — the shell every demo shares (MOBILE.md §3): a top bar with the date and a
 * three-week date strip, a bottom thumb bar (previous day / today / filters / next day), the filter, detail and
 * layout bottom sheets, swipe to change day, the empty state, the page footer. A demo supplies the content area:
 *   MChrome.start({ id: "agenda", render(ctx) { return nodes }, after(ctx, opts), tools(ctx), extra,
 *                   topRegions: true (region buttons in the top bar), menu: false (no layout menu), title })
 */
(function () {
  "use strict";

  const C = window.MCore;
  const CAL = window.CinemaCalendar;
  const m = C.model(window.CINEMA_DATA);
  const store = (() => { try { return window.localStorage; } catch (_) { return null; } })();
  const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)");
  let lang = C.initialLang(location.hash, store, navigator.language);
  let t = C.translator(lang);
  let today = C.todayKey();
  let shownToday = today;
  let state = C.parseHash(location.hash, m, today, store);
  let cfg = null;
  let sheet = null;                 // the open bottom sheet: {refresh, opener}
  let ignorePop = false;
  let lastStarted = -1;
  let stripFirst = true;
  const ui = {};

  // ---------- DOM helpers ----------
  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "style") node.style.cssText = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat(Infinity)) {
      if (c == null || c === false) continue;
      node.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return node;
  }

  const ICONS = {
    prev: '<path d="M15 5l-7 7 7 7"/>',
    next: '<path d="M9 5l7 7-7 7"/>',
    filter: '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
    down: '<path d="M7 10l5 5 5-5"/>',
    rows: '<path d="M4 6h16M4 10h16M4 14h16M4 18h16"/>',
    search: '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/>',
  };
  function icon(name, size = 20) {
    const s = el("span", { class: "m-ic", "aria-hidden": "true" });
    s.innerHTML = `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICONS[name]}</svg>`;
    return s;
  }

  const dot = (v) => el("span", { class: "dot", style: `--c:${(v && v.color) || "#888"}` });

  /** "旧数据 · 2 天前" / "抓取失败" / "via screenslate" beside a cinema's name. */
  function venueBadge(v) {
    if (!v) return null;
    if (v.status === "failed") return el("span", { class: "m-badge failed", title: v.error || "" }, t("failed"));
    if (v.status === "ok" && v.source && v.source !== "primary") return el("span", { class: "m-badge via" }, `via ${v.source}`);
    if (v.status === "stale") return el("span", { class: "m-badge", title: v.error || "" }, t("stale", C.relTime(v.fetched_at, t)));
    return null;
  }

  /** A start-time button that opens the detail sheet; on-film screenings carry their gauge. */
  function timePill(s, now = new Date(), cls = "") {
    const label = C.timeLabel(s.start, m.tzOf(s));
    const past = new Date(s.start) < now;
    return el("button", {
      type: "button", class: `m-time${past ? " past" : ""}${cls ? " " + cls : ""}`,
      "aria-label": `${label} ${s.title}${past ? " · " + t("startedTag") : ""}`, onclick: () => showDetail(s),
    }, label, C.isOnFilm(s) ? el("small", {}, s.format) : null);
  }

  /** Press and hold (or right-click) runs `fn` and swallows the click that follows. */
  function longPress(node, fn) {
    let timer = null, fired = false, x0 = 0, y0 = 0;
    const fire = () => { clearTimeout(timer); fired = true; if (navigator.vibrate) navigator.vibrate(12); fn(); };
    node.addEventListener("touchstart", (e) => {
      fired = false; x0 = e.touches[0].clientX; y0 = e.touches[0].clientY;
      clearTimeout(timer); timer = setTimeout(fire, 500);
    }, { passive: true });
    node.addEventListener("touchmove", (e) => {
      if (Math.hypot(e.touches[0].clientX - x0, e.touches[0].clientY - y0) > 8) clearTimeout(timer);
    }, { passive: true });
    node.addEventListener("touchend", (e) => { clearTimeout(timer); if (fired && e.cancelable) e.preventDefault(); });
    node.addEventListener("touchcancel", () => clearTimeout(timer));
    node.addEventListener("contextmenu", (e) => { e.preventDefault(); if (!fired) fire(); });
    node.addEventListener("click", (e) => { if (fired) { fired = false; e.stopImmediatePropagation(); e.preventDefault(); } }, true);
  }

  // ---------- state ----------
  function writeHash() {
    const h = C.buildHash(state, m, today);
    if (location.hash !== h) history.replaceState(history.state, "", h);
  }

  function update(patch, opts = {}) {
    const dayChanged = !!patch.day && patch.day !== state.day;
    Object.assign(state, patch);
    if (patch.venues) C.saveVenues(store, state, m);
    if (patch.regions) C.saveRegions(store, state);
    writeHash();
    render({ dayChanged, ...opts });
  }

  const go = (day) => update({ day, hl: "" });
  const minDay = () => stripDays()[0];
  function step(n) {
    const d = C.shiftDay(state.day, n);
    if (d >= minDay()) go(d);
  }
  const filtersOn = () => state.film || state.subs || state.upcoming || state.specials || !!state.q;
  const allVenues = () => new Set(m.active.map((v) => v.id));
  const selectAll = () => update({ venues: allVenues(), regions: new Set(m.regions) });
  const shownVenues = () => m.active.filter((v) => C.shown(state, m, v.id));

  function onlyVenue(v) {
    const before = { venues: new Set(state.venues), regions: new Set(state.regions) };
    update({ venues: new Set([v.id]), regions: new Set([...state.regions, m.regionOf(v)]) });
    toast(t("nowOnly", v.short || v.name), t("undo"), () => update(before));
  }

  function toggleVenue(v) {
    const r = m.regionOf(v);
    const venues = new Set(state.venues);
    if (!state.regions.has(r)) { venues.add(v.id); return update({ venues, regions: new Set([...state.regions, r]) }); }
    venues.has(v.id) ? venues.delete(v.id) : venues.add(v.id);
    update({ venues });
  }

  /** As the main page: a region switched on shows all of its cinemas; the others keep their own choice. */
  function toggleRegion(r, only = false) {
    const withVenues = new Set([...state.venues, ...m.active.filter((v) => m.regionOf(v) === r).map((v) => v.id)]);
    if (only) return update({ regions: new Set([r]), venues: withVenues });
    const regions = new Set(state.regions);
    if (regions.has(r)) { regions.delete(r); return update({ regions }); }
    regions.add(r);
    update({ regions, venues: withVenues });
  }

  /** Every region on; one that was off comes back with all of its cinemas (as on the main page). */
  function showAllRegions() {
    const back = m.active.filter((v) => !state.regions.has(m.regionOf(v))).map((v) => v.id);
    update({ regions: new Set(m.regions), venues: new Set([...state.venues, ...back]) });
  }

  /** A region button: only that region; tapping the only one shown brings every region back. */
  const pickRegion = (r) => (state.regions.size === 1 && state.regions.has(r) ? showAllRegions() : toggleRegion(r, true));

  function setLang(l) {
    lang = l; t = C.translator(l);
    try { store && store.setItem(C.LS.lang, l); } catch (_) { /* ignore */ }
    render({});
  }

  // ---------- shell ----------
  function build() {
    ui.titleMain = el("span", { class: "m-title-main" });
    ui.titleRel = el("span", { class: "m-title-rel" });
    ui.dateInput = el("input", {
      type: "date", class: "m-date-input",
      onchange: (e) => C.validDay(e.target.value) && go(e.target.value < minDay() ? minDay() : e.target.value),
      onclick: (e) => { try { e.target.showPicker(); } catch (_) { /* the native control opens itself */ } },
    });
    ui.tools = el("div", { class: "m-tools" });
    ui.regions = cfg.topRegions && m.regions.length > 1 ? el("div", { class: "m-rseg", role: "group" }) : null;
    ui.menuBtn = cfg.menu === false ? null : el("button", { type: "button", class: "m-hbtn", "aria-haspopup": "dialog", onclick: openMenu });
    ui.langBtn = el("button", { type: "button", class: "m-hbtn m-lang", onclick: () => setLang(lang === "zh" ? "en" : "zh") });
    ui.strip = el("div", { class: "m-strip", role: "group" });
    ui.top = el("header", { class: "m-top" },
      el("div", { class: "m-row1" },
        el("div", { class: "m-titlebox" },                // the native date picker lies invisibly over the title only
          el("div", { class: "m-title", "aria-hidden": "true" }, ui.titleMain, ui.titleRel, icon("down", 16)), ui.dateInput),
        ui.tools, ui.regions, ui.menuBtn, ui.langBtn),
      ui.strip);
    ui.main = el("main", { class: "m-main", id: "m-main" });
    ui.prevLbl = el("span");
    ui.nextLbl = el("span");
    ui.prev = el("button", { type: "button", class: "m-b m-b-step", onclick: () => step(-1) }, icon("prev"), ui.prevLbl);
    ui.next = el("button", { type: "button", class: "m-b m-b-step", onclick: () => step(1) }, ui.nextLbl, icon("next"));
    ui.today = el("button", { type: "button", class: "m-b", onclick: () => go(today) });
    ui.extra = cfg.extra ? el("button", { type: "button", class: "m-b", onclick: () => cfg.extra.onClick(context()) }) : null;
    ui.filterLbl = el("span");
    ui.filterN = el("span", { class: "m-b-n" });
    ui.filter = el("button", { type: "button", class: "m-b m-b-filter", "aria-haspopup": "dialog", onclick: () => openFilters() },
      el("span", { class: "m-b-pill" }, icon("filter", 18), ui.filterLbl, ui.filterN));
    ui.bottom = el("nav", { class: "m-bottom" + (ui.extra ? " five" : "") }, ui.prev, ui.today, ui.extra, ui.filter, ui.next);
    ui.scrim = el("div", { class: "m-scrim", onclick: () => closeSheet() });
    ui.sheetBody = el("div", { class: "m-sheet-body" });
    ui.sheet = el("div", { class: "m-sheet", role: "dialog", "aria-modal": "true", tabindex: "-1" },
      el("div", { class: "m-grab", "aria-hidden": "true" }), ui.sheetBody);
    ui.toast = el("div", { class: "m-toast", role: "status", "aria-live": "polite" });
    document.body.classList.add("m-body");
    document.body.dataset.demo = cfg.id;
    document.body.append(ui.top, ui.main, ui.bottom, ui.scrim, ui.sheet, ui.toast);
    dragToClose();
  }

  /** The strip: from a week back (no earlier than the first day with data) to two weeks ahead. */
  function stripDays() {
    const first = m.days[0] || today;
    let a = C.shiftDay(today, -7);
    if (first > a) a = first < today ? first : today;
    if (state.day < a) a = state.day;
    let b = C.shiftDay(today, 13);
    if (state.day > b) b = state.day;
    const out = [];
    for (let d = a; d <= b; d = C.shiftDay(d, 1)) out.push(d);
    return out;
  }

  function renderTop(now) {
    const demo = C.DEMOS.find((d) => d.id === cfg.id);
    const rel = C.relDay(state.day, today, t);     // "今天" / "明天" stand in for the weekday (the strip shows it)
    if (lang === "zh") {
      ui.titleMain.textContent = `${C.monthDay(state.day, lang)} `;
      ui.titleRel.textContent = rel || C.weekday(state.day, lang);
    } else {
      ui.titleMain.textContent = rel ? "" : C.dayTitle(state.day, lang);          // "Tomorrow, Oct 9" / "Sun, Oct 11"
      ui.titleRel.textContent = rel ? `${rel}, ${C.monthDay(state.day, lang)}` : "";
    }
    ui.titleRel.classList.toggle("rel", !!rel);
    ui.dateInput.value = state.day;
    ui.dateInput.min = minDay();
    if (m.days.length) ui.dateInput.max = m.days[m.days.length - 1];
    ui.dateInput.setAttribute("aria-label", `${t("pickDate")}: ${C.dayTitle(state.day, lang)}${rel ? " · " + rel : ""}`);
    if (ui.menuBtn) {
      ui.menuBtn.replaceChildren(el("span", { class: "m-hbtn-in" }, demo ? demo[lang] : cfg.id, icon("down", 14)));
      ui.menuBtn.setAttribute("aria-label", `${t("demos")}: ${demo ? demo[lang] : cfg.id}`);
    }
    if (ui.regions) {
      const allOn = m.regions.every((r) => state.regions.has(r));
      const seg = (label, on, onclick) => el("button", { type: "button", class: on ? "on" : null, "aria-pressed": String(on), onclick }, label);
      ui.regions.setAttribute("aria-label", t("regions"));
      ui.regions.replaceChildren(seg(t("all"), allOn, showAllRegions),
        ...m.regions.map((r) => seg(r, !allOn && state.regions.has(r), () => pickRegion(r))));
    }
    ui.langBtn.replaceChildren(el("span", { class: "m-hbtn-in" }, lang === "zh" ? "EN" : "中"));
    ui.langBtn.setAttribute("aria-label", t("lang"));
    ui.langBtn.lang = lang === "zh" ? "en" : "zh-CN";
    ui.tools.replaceChildren(...[].concat(cfg.tools ? cfg.tools(context()) : []).filter(Boolean));

    const days = stripDays();
    const counts = C.dayCounts(m, state, days, now, today);
    ui.strip.setAttribute("aria-label", t("dateStrip"));
    ui.strip.replaceChildren(...days.map((d) => {
      const n = counts[d];
      const dn = +d.slice(8);
      const cls = ["m-day", d === state.day && "sel", d === today && "today", d < today && "past", !n && "zero"].filter(Boolean).join(" ");
      return el("button", {
        type: "button", class: cls, "data-day": d, "aria-pressed": String(d === state.day),
        "aria-label": `${C.dayTitle(d, lang)}${C.relDay(d, today, t) ? " · " + C.relDay(d, today, t) : ""} · ${t("shows", n)}`,
        onclick: () => go(d),
      },
        el("span", { class: "wd" }, dn === 1 && d !== today ? C.monthShort(d, lang) : C.weekday(d, lang)),
        el("span", { class: "dn" }, dn),
        el("span", { class: "ct" }, n || "·"));
    }));
    const sel = ui.strip.querySelector(".sel");
    if (stripFirst) {                                       // first view: today at the left edge, yesterday peeking
      stripFirst = false;
      const td = ui.strip.querySelector(".today") || sel;
      if (td) ui.strip.scrollLeft = Math.max(0, td.offsetLeft - 30);
    }
    if (sel) {
      const l = sel.offsetLeft, r = l + sel.offsetWidth, sl = ui.strip.scrollLeft, w = ui.strip.clientWidth;
      if (l < sl + 8) ui.strip.scrollLeft = l - 30;
      else if (r > sl + w - 8) ui.strip.scrollLeft = r - w + 30;
    }
  }

  function renderBottom() {
    const prev = C.shiftDay(state.day, -1), next = C.shiftDay(state.day, 1);
    ui.prev.disabled = prev < minDay();
    ui.prevLbl.textContent = C.weekday(prev, lang);
    ui.prev.setAttribute("aria-label", `${t("prevDay")}: ${C.dayTitle(prev, lang)}`);
    ui.nextLbl.textContent = C.weekday(next, lang);
    ui.next.setAttribute("aria-label", `${t("nextDay")}: ${C.dayTitle(next, lang)}`);
    ui.today.textContent = t("today");
    ui.today.disabled = state.day === today;
    if (ui.extra) ui.extra.textContent = cfg.extra.label(t);
    ui.filterLbl.textContent = t("filter");
    const nShown = shownVenues().length;
    ui.filterN.textContent = ui.extra && nShown === m.active.length ? "" : t("shown", nShown, m.active.length);   // five buttons: count only when some are off
    ui.filter.classList.toggle("active", filtersOn());
    ui.bottom.setAttribute("aria-label", t("bottomBar"));
  }

  function context(list, now = new Date()) {
    return {
      C, m, t, lang, el, icon, dot, store, state, now, today, list: list || C.visible(m, state, state.day, now, today),
      day: state.day, isToday: state.day === today, main: ui.main, top: ui.top,
      update, go, showDetail, toast, longPress, timePill, venueBadge, onlyVenue, empty: emptyState,
      refresh: () => render({ keep: true }), quickFilters: () => quickFilters(now), footer,
    };
  }

  const startedCount = (list, now) => list.reduce((n, s) => n + (new Date(s.start) < now ? 1 : 0), 0);

  function render(opts = {}) {
    const now = new Date();
    today = C.todayKey(now);
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
    document.title = cfg.title || `${(C.DEMOS.find((d) => d.id === cfg.id) || {})[lang] || ""} · Corridor Showtimes`;
    renderTop(now);
    renderBottom();
    const ctx = context(null, now);
    const out = m.data.generated_at ? cfg.render(ctx) : emptyState(t("noData"));
    ui.main.replaceChildren(...[].concat(out).filter(Boolean));
    const chips = ui.main.querySelector(".m-chips[data-noswipe]");
    if (chips) chips.scrollLeft = chipScroll;           // a tap far along the row keeps the row where it was
    if (opts.dayChanged) window.scrollTo(0, 0);
    if (cfg.after) cfg.after(ctx, opts);
    if (sheet && sheet.refresh) sheet.refresh();
    lastStarted = startedCount(ctx.list, now);
  }

  function emptyState(msg) {
    const box = el("div", { class: "m-empty" });
    if (!shownVenues().length) {
      box.append(el("p", {}, t("noVenues")), el("button", { type: "button", class: "m-btn", onclick: selectAll }, t("selectAll")));
      return box;
    }
    box.append(el("p", {}, msg || t("dayEmpty")));
    const acts = el("div", { class: "m-empty-acts" });
    if (filtersOn()) {
      acts.append(el("button", { type: "button", class: "m-btn ghost",
        onclick: () => update({ film: false, subs: false, upcoming: false, specials: false, q: "" }) }, t("clearFilters")));
    }
    const next = C.nearestDay(m, state, state.day, 1, new Date(), today);
    if (next) {
      acts.append(el("button", { type: "button", class: "m-btn", onclick: () => go(next) },
        next === C.shiftDay(today, 1) ? t("seeTomorrow") : t("seeDay", C.monthDay(next, lang))));
    }
    box.append(acts);
    return box;
  }

  // ---------- bottom sheets ----------
  function openSheet(children, opts = {}) {
    const wasOpen = !!sheet;
    sheet = { refresh: opts.refresh || null, opener: wasOpen ? sheet.opener : document.activeElement };
    ui.sheetBody.replaceChildren(...children.filter(Boolean));
    ui.sheet.className = "m-sheet open" + (opts.cls ? " " + opts.cls : "");
    ui.sheet.setAttribute("aria-label", opts.label || "");
    ui.sheetBody.scrollTop = 0;
    if (sheet.refresh) sheet.refresh();
    if (!wasOpen) {
      ui.scrim.classList.add("open");
      document.documentElement.classList.add("m-locked");
      history.pushState({ mSheet: 1 }, "", location.href);    // the phone's Back closes the sheet
    }
    ui.sheet.focus({ preventScroll: true });
  }

  function closeSheet(fromPop = false) {
    if (!sheet) return;
    const opener = sheet.opener;
    sheet = null;
    ui.sheet.classList.remove("open");
    ui.scrim.classList.remove("open");
    document.documentElement.classList.remove("m-locked");
    if (!fromPop && history.state && history.state.mSheet) { ignorePop = true; history.back(); }
    if (opener && opener.focus && document.contains(opener)) opener.focus({ preventScroll: true });
  }

  /** Pull the sheet down by its top (or by its content when that is scrolled to the top) to close it. */
  function dragToClose() {
    let y0 = null, dy = 0;
    ui.sheet.addEventListener("touchstart", (e) => {
      y0 = null;
      if (e.touches.length !== 1 || e.target.closest("input")) return;
      if (e.target.closest(".m-sheet-body") && ui.sheetBody.scrollTop > 0) return;
      y0 = e.touches[0].clientY; dy = 0;
    }, { passive: true });
    ui.sheet.addEventListener("touchmove", (e) => {
      if (y0 == null) return;
      dy = e.touches[0].clientY - y0;
      if (dy <= 0) { ui.sheet.style.transform = ""; return; }
      if (e.cancelable) e.preventDefault();
      ui.sheet.style.transition = "none";
      ui.sheet.style.transform = `translateY(${dy}px)`;
    }, { passive: false });
    const end = () => {
      if (y0 == null) return;
      y0 = null;
      ui.sheet.style.transition = "";
      ui.sheet.style.transform = "";
      if (dy > 90) closeSheet();
    };
    ui.sheet.addEventListener("touchend", end);
    ui.sheet.addEventListener("touchcancel", end);
  }

  function sheetHead(title, btnLabel) {
    return el("div", { class: "m-sheet-head" }, title,
      el("button", { type: "button", class: "m-btn small", onclick: () => closeSheet() }, btnLabel || t("done")));
  }

  /** Regions (unless they sit in the top bar), then the four switches and search, as rows of buttons above
   *  the content: one tap, no sheet. */
  let chipScroll = 0;
  function quickFilters(now = new Date()) {
    const day = m.forDay(state.day).filter((s) => C.passes(s, state, now, today));
    const allOn = m.regions.every((r) => state.regions.has(r));
    // what a region shows once picked: its chosen cinemas, or all of them when it is off now
    const countIn = (r) => day.filter((s) => {
      const v = m.venueById[s.venue_id] || {};
      return m.regionOf(v) === r && (!state.regions.has(r) || state.venues.has(v.id));
    }).length;
    const chip = (label, on, onclick, n, cls = "") => el("button", {
      type: "button", class: `m-chip${cls}${on ? " on" : ""}`, "aria-pressed": String(on), onclick,
    }, label, n != null ? el("span", { class: "n" }, n) : null);
    const regions = m.regions.length > 1 && !ui.regions ? el("div", { class: "m-chips regions", role: "group", "aria-label": t("regions") },
      chip(t("all"), allOn, showAllRegions, m.regions.reduce((n, r) => n + countIn(r), 0)),
      m.regions.map((r) => chip(r, !allOn && state.regions.has(r), () => pickRegion(r), countIn(r)))) : null;
    const switches = el("div", { class: "m-chips", role: "group", "aria-label": t("filter"), "data-noswipe": "",
      onscroll: (e) => { chipScroll = e.currentTarget.scrollLeft; } },
      [["film", "onFilm"], ["subs", "subs"], ["specials", "specials"], ["upcoming", "upcoming"]].map(([k, label]) =>
        chip(t(label), state[k], () => update({ [k]: !state[k] }), null, " tg")),
      state.q
        ? el("button", { type: "button", class: "m-chip on", "aria-label": `${t("clearSearch")}: ${state.q}`, onclick: () => update({ q: "" }) },
          `“${state.q}”`, el("span", { class: "x", "aria-hidden": "true" }, "×"))
        : el("button", { type: "button", class: "m-chip", "aria-haspopup": "dialog", onclick: () => openFilters(true) }, icon("search", 16), t("searchShort")));
    return el("div", { class: "m-qf" }, regions, switches);
  }

  /** The end of the page: freshness, language, source and the TMDB credit its terms ask for. */
  function footer() {
    const gen = m.data.generated_at;
    return el("footer", { class: "m-foot" },
      el("p", {}, [gen ? t("updated", C.relTime(gen, t)) : t("noData"),
        m.days.length ? t("range", m.days[0], m.days[m.days.length - 1]) : ""].filter(Boolean).join(" · ")),
      el("p", { class: "m-foot-links" },
        el("button", { type: "button", class: "m-link", lang: lang === "zh" ? "en" : "zh-CN", onclick: () => setLang(lang === "zh" ? "en" : "zh") }, t("lang")),
        el("a", { class: "m-link", href: "https://github.com/Marc506/corridor-showtimes", target: "_blank", rel: "noopener" }, t("source"))),
      el("p", { class: "m-foot-credits" }, t("credits")[0],
        el("a", { href: "https://www.themoviedb.org/", target: "_blank", rel: "noopener" }, "TMDB"), t("credits")[1]));
  }

  function openFilters(focusSearch = false) {
    const count = el("strong", { class: "m-f-count", "aria-live": "polite" });
    let timer;
    const q = el("input", {
      type: "search", class: "m-search", placeholder: t("search"), "aria-label": t("search"),
      enterkeyhint: "search", autocomplete: "off", spellcheck: "false",
      oninput: () => { clearTimeout(timer); timer = setTimeout(() => update({ q: q.value.trim() }), 200); },
      onkeydown: (e) => { if (e.key === "Enter") q.blur(); },
    });
    q.value = state.q;
    const toggles = el("div", { class: "m-f-toggles" });
    const venues = el("div", { class: "m-f-venues" });
    const fill = () => {
      const now = new Date();
      count.textContent = t("venuesShows", shownVenues().length, C.visible(m, state, state.day, now, today).length);
      toggles.replaceChildren(...[["film", "onFilm"], ["subs", "subs"], ["specials", "specials"], ["upcoming", "upcoming"]].map(([k, label]) =>
        el("button", { type: "button", class: "m-toggle" + (state[k] ? " on" : ""), "aria-pressed": String(state[k]),
          onclick: () => update({ [k]: !state[k] }) }, el("span", { class: "m-check", "aria-hidden": "true" }), t(label))));
      const counts = {};      // per cinema for this day, every filter but the cinema choice
      for (const s of m.forDay(state.day)) if (C.passes(s, state, now, today)) counts[s.venue_id] = (counts[s.venue_id] || 0) + 1;
      const multi = m.regions.length > 1;
      venues.replaceChildren(
        el("div", { class: "m-f-vhead" }, el("span", { class: "m-label" }, t("cinemas")),
          el("button", { type: "button", class: "m-link", onclick: selectAll }, t("selectAll")),
          el("button", { type: "button", class: "m-link", onclick: () => update({ venues: new Set() }) }, t("clear"))),
        el("p", { class: "m-hint" }, t("longPress")),
        ...m.regions.map((r) => {
          const on = state.regions.has(r);
          return el("section", { class: "m-f-region" + (on ? "" : " off") },
            multi ? el("div", { class: "m-f-rhead" },
              el("button", { type: "button", class: "m-toggle small" + (on ? " on" : ""), "aria-pressed": String(on), onclick: () => toggleRegion(r) },
                el("span", { class: "m-check", "aria-hidden": "true" }), r),
              el("button", { type: "button", class: "m-link", onclick: () => toggleRegion(r, true) }, t("onlyRegion", r))) : null,
            el("div", { class: "m-f-grid" }, m.active.filter((v) => m.regionOf(v) === r).map((v) => {
              const vOn = C.shown(state, m, v.id);
              const b = el("button", { type: "button", class: "m-vchip" + (vOn ? " on" : ""), "aria-pressed": String(vOn),
                style: `--c:${v.color}`, onclick: () => toggleVenue(v) },
                el("span", { class: "dot" }), el("span", { class: "nm" }, v.name), el("span", { class: "n" }, counts[v.id] || 0),
                v.status === "stale" || v.status === "failed" || (v.source && v.source !== "primary") ? el("span", { class: "warn " + v.status }) : null);
              longPress(b, () => onlyVenue(v));
              return b;
            })));
        }));
    };
    openSheet([sheetHead(count), q, toggles, venues], { label: t("filter"), refresh: fill, cls: "filters" });
    if (focusSearch) q.focus({ preventScroll: true });
  }

  function mapsUrl(place) {
    return "https://www.google.com/maps/search/?api=1&query=" + encodeURIComponent([place.name, place.address].filter(Boolean).join(", "));
  }

  function showDetail(s) {
    const v = m.venueById[s.venue_id] || {};
    const tz = m.tzOf(s);
    const now = new Date();
    const started = new Date(s.start) < now;
    const meta = [s.director, s.year, s.runtime_min ? t("minutes", s.runtime_min) : null, s.format, s.language].filter(Boolean).join(" · ");
    const twins = m.twinsOf(s).filter((x) => x !== s);
    const others = m.forDay(s.day).filter((x) => x.venue_id === s.venue_id && x.title === s.title && x.start !== s.start);
    const alsoAt = C.visible(m, state, s.day, now, today).filter((x) => x.venue_id !== s.venue_id &&
      Date.parse(x.start) === Date.parse(s.start) && C.fold(x.title) === C.fold(s.title));
    const place = CAL ? CAL.placeFor(v, s.screen, s) : { name: v.name, address: (v.location || {}).address || null };
    const rel = C.relDay(s.day, today, t);
    const calNote = el("p", { class: "m-hint", hidden: true });
    const note = (msg) => { calNote.textContent = msg; calNote.hidden = false; };
    const calBox = CAL ? el("div", { class: "m-d-cal", hidden: true },
      el("button", { type: "button", class: "m-btn ghost", onclick: () => {
        if (CAL.iosNeedsSafari()) return note(t("calSafari"));
        CAL.download(CAL.toICS(CAL.eventFor(s, v, lang)), CAL.fileName(s));
        if (!CAL.isIOS()) note(t("calSaved"));
      } }, t("appleCal")),
      el("a", { class: "m-btn ghost", href: CAL.googleUrl(CAL.eventFor(s, v, lang), CAL.isMobile()), target: "_blank", rel: "noopener" }, t("googleCal"))) : null;
    const calBtn = CAL ? el("button", { type: "button", class: "m-btn ghost", "aria-expanded": "false", onclick: () => {
      calBox.hidden = !calBox.hidden;
      calBtn.setAttribute("aria-expanded", String(!calBox.hidden));
    } }, t("addCal")) : null;
    openSheet([
      el("div", { class: "m-d-venue" }, dot(v), el("span", {}, [v.name, s.screen && s.screen !== v.name ? s.screen : null].filter(Boolean).join(" · ")), venueBadge(v)),
      el("h2", { class: "m-d-title" }, s.title),
      el("div", { class: "m-d-time" + (started ? " past" : "") },
        el("span", { class: "tm" }, C.timeLabel(s.start, tz), s.end ? ` – ${C.timeLabel(s.end, tz)}` : ""),
        el("span", { class: "m-d-day" }, ` · ${C.dayTitle(s.day, lang)}${rel ? " · " + rel : ""}`)),
      meta || !(s.runtime_min || s.end) ? el("div", { class: "m-d-meta" }, meta, s.runtime_min || s.end ? "" : `${meta ? " · " : ""}${t("runtimeUnknown")}`) : null,
      s.series ? el("div", { class: "m-d-series" }, s.series) : null,
      s.note ? el("div", { class: "m-d-note" }, s.note) : null,
      s.source && s.source !== "primary" ? el("p", { class: "m-hint" }, t("viaTag", s.source)) : null,
      el("div", { class: "m-d-actions" },
        s.ticket_url ? el("a", { class: "m-btn", href: s.ticket_url, target: "_blank", rel: "noopener" }, t("tickets")) : null,
        s.detail_url ? el("a", { class: "m-btn ghost", href: s.detail_url, target: "_blank", rel: "noopener" }, t("details")) : null,
        calBtn),
      calBox, calNote,
      twins.length ? el("div", { class: "m-d-twins" }, t("alsoScreen", ""), twins.map((x) =>
        el("a", { class: "m-link", href: x.ticket_url || x.detail_url || "#", target: "_blank", rel: "noopener" }, x.screen || x.title))) : null,
      alsoAt.length ? el("div", { class: "m-d-others" }, el("div", { class: "m-label" }, t("sameTime")),
        el("div", { class: "m-times" }, alsoAt.map((x) => el("button", { type: "button", class: "m-time", onclick: () => showDetail(x) },
          dot(m.venueById[x.venue_id]), (m.venueById[x.venue_id] || {}).short || x.venue_id)))) : null,
      others.length ? el("div", { class: "m-d-others" }, el("div", { class: "m-label" }, t("otherTimes")),
        el("div", { class: "m-times" }, others.map((x) => timePill(x, now)))) : null,
      place.address ? el("a", { class: "m-d-addr", href: mapsUrl(place), target: "_blank", rel: "noopener" },
        el("span", { class: "m-label" }, t("address")), place.name && place.name !== v.name ? `${place.name} · ` : "", place.address) : null,
      el("div", { class: "m-d-links" },
        el("button", { type: "button", class: "m-link", onclick: () => { closeSheet(); update({ q: s.title }); } }, t("onlyFilm")),
        el("button", { type: "button", class: "m-link", onclick: () => { closeSheet(); onlyVenue(v); } }, t("onlyVenue", v.short || v.name)),
        v.website ? el("a", { class: "m-link", href: v.website, target: "_blank", rel: "noopener" }, t("website")) : null),
    ], { label: s.title, cls: "detail" });
  }

  function openMenu() {
    const hash = C.buildHash(state, m, today);
    const gen = m.data.generated_at;
    openSheet([
      sheetHead(el("strong", {}, t("demos")), t("close")),
      el("nav", { class: "m-demos" }, C.DEMOS.map((d) => el("a", {
        class: "m-demo" + (d.id === cfg.id ? " cur" : ""), href: `../${d.id}/index.html${hash}`, "aria-current": d.id === cfg.id ? "page" : null,
      }, el("strong", {}, d[lang]), el("span", {}, d[lang + "D"])))),
      el("div", { class: "m-menu-links" },
        el("a", { class: "m-btn ghost", href: "../index.html" }, t("chooser")),
        el("button", { type: "button", class: "m-btn ghost", lang: lang === "zh" ? "en" : "zh-CN", onclick: () => { closeSheet(); setLang(lang === "zh" ? "en" : "zh"); } }, t("lang"))),
      el("p", { class: "m-hint" }, [gen ? t("updated", C.relTime(gen, t)) : t("noData"),
        m.days.length ? t("range", m.days[0], m.days[m.days.length - 1]) : ""].filter(Boolean).join(" · ")),
    ], { label: t("menu"), cls: "menu" });
  }

  let toastTimer;
  function toast(msg, action, onAction) {
    clearTimeout(toastTimer);
    ui.toast.replaceChildren(el("span", {}, msg), action ? el("button", { type: "button", class: "m-link",
      onclick: () => { ui.toast.classList.remove("show"); onAction(); } }, action) : null);
    ui.toast.classList.add("show");
    toastTimer = setTimeout(() => ui.toast.classList.remove("show"), 4500);
  }

  // ---------- swipe to change day ----------
  function swipe(area) {
    let x0 = null, y0 = 0, dx = 0, axis = null;
    area.addEventListener("touchstart", (e) => {
      x0 = null;
      if (sheet || e.touches.length !== 1 || e.target.closest("[data-noswipe]")) return;
      const p = e.touches[0];
      if (p.clientX < 24 || p.clientX > window.innerWidth - 24) return;   // the screen edges belong to the browser's Back
      x0 = p.clientX; y0 = p.clientY; dx = 0; axis = null;
    }, { passive: true });
    area.addEventListener("touchmove", (e) => {
      if (x0 == null) return;
      const p = e.touches[0];
      dx = p.clientX - x0;
      const dy = p.clientY - y0;
      if (!axis) {
        if (Math.abs(dx) < 10 && Math.abs(dy) < 10) return;
        axis = Math.abs(dx) > Math.abs(dy) * 1.3 ? "x" : "y";
      }
      if (axis === "x" && !REDUCED.matches) { area.style.transition = "none"; area.style.transform = `translateX(${dx / 3}px)`; }
    }, { passive: true });
    const end = () => {
      if (x0 == null) return;
      x0 = null;
      if (axis !== "x") return;
      const dir = dx < -60 ? 1 : dx > 60 ? -1 : 0;
      const target = C.shiftDay(state.day, dir);
      if (!dir || target < minDay()) {
        area.style.transition = "transform 150ms ease-out";
        area.style.transform = "";
        return;
      }
      slideTo(target, dir);
    };
    area.addEventListener("touchend", end);
    area.addEventListener("touchcancel", end);
  }

  function slideTo(day, dir) {
    const a = ui.main;
    if (REDUCED.matches) { a.style.transform = ""; return go(day); }
    a.style.transition = "transform 150ms ease-in, opacity 150ms ease-in";
    a.style.transform = `translateX(${-dir * 30}%)`;
    a.style.opacity = "0";
    setTimeout(() => {
      a.style.transition = "none";
      go(day);
      a.style.transform = `translateX(${dir * 30}%)`;
      void a.offsetWidth;
      a.style.transition = "transform 150ms ease-out, opacity 150ms ease-out";
      a.style.transform = "";
      a.style.opacity = "";
      setTimeout(() => { a.style.transition = ""; }, 170);
    }, 150);
  }

  // ---------- wiring ----------
  /** The date changed since the page was drawn (midnight, or back from the background): follow it. */
  function followToday() {
    const now = C.todayKey();
    if (now === shownToday) return false;
    const was = state.day === shownToday;
    shownToday = now;
    today = now;
    if (!was) return false;
    go(now);
    return true;
  }

  function start(config) {
    cfg = config;
    if (history.state && history.state.mSheet) history.replaceState(null, "", location.href);
    build();
    if (cfg.swipe !== false) swipe(ui.main);
    writeHash();
    render({ first: true });
    window.addEventListener("popstate", () => {
      if (!ignorePop && !sheet) return;    // a plain hash change: "hashchange" below follows it
      if (ignorePop) ignorePop = false;
      else closeSheet(true);
      writeHash();                         // the entry under the sheet's may carry an older hash
    });
    window.addEventListener("hashchange", () => {
      if (location.hash === C.buildHash(state, m, today)) return;
      state = C.parseHash(location.hash, m, today, store);
      render({ dayChanged: true });
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && sheet) return closeSheet();
      if (sheet || e.target.matches("input, textarea") || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "ArrowLeft") step(-1);
      if (e.key === "ArrowRight") step(1);
    });
    setInterval(() => {
      if (followToday()) return;
      const now = new Date();
      if (cfg.tick) cfg.tick(context(null, now));
      if (!sheet && startedCount(C.visible(m, state, state.day, now, today), now) !== lastStarted) render({ keep: true });
    }, 30e3);
    let hiddenAt = null;
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) { hiddenAt = Date.now(); return; }
      if (hiddenAt && Date.now() - hiddenAt > 60 * 60e3) return location.reload();   // pick up the twice-daily data
      hiddenAt = null;
      followToday();
    });
  }

  window.MChrome = { start, el, icon };
})();
