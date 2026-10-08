/* Agenda (MOBILE.md §4 A) — every selected cinema in one column by start time, grouped by hour.
 * Screenings that have started fold into one row above a "now" line; "Compact" puts each on one line. */
(function () {
  "use strict";
  const { el } = window.MChrome;
  const KEY = "cinema.m.agenda.dense";
  let dense = (() => { try { return localStorage.getItem(KEY) === "1"; } catch (_) { return false; } })();
  let showPast = false;
  let lastDay = null;

  /** One row per film and start time: a wide release starting together at several cinemas (or on two
   *  screens of one) is one row listing those cinemas. */
  function sameStart(list, C) {
    const rows = new Map();
    for (const s of list) {
      const k = `${Date.parse(s.start)}|${C.fold(s.title)}`;
      if (!rows.has(k)) rows.set(k, []);
      rows.get(k).push(s);
    }
    return [...rows.values()];
  }

  /** Kept light (about six elements a row) so the busiest day stays under 1,500 nodes: the am / pm and the
   *  cinema dots are drawn by CSS from data-ap and --c. */
  function row(ctx, group, counts, past) {
    const { C, m } = ctx;
    const s = group[0];
    const venues = [...new Set(group.map((x) => x.venue_id))].map((id) => m.venueById[id] || {});
    const same = group.length - venues.length;          // extra screens at a cinema already listed
    const tp = C.timeParts(s.start, m.tzOf(s));
    const hl = ctx.state.hl && C.fold(ctx.state.hl) === C.fold(s.title);
    const cls = "ag-row" + (dense ? " d" : "") + (past ? " past" : "") + (hl ? " hl" : "");
    const time = el("span", { class: "ag-time", "data-ap": tp.ap }, tp.hm);
    const cinema = (v, more) => el("span", { class: "ag-v", style: `--c:${v.color}` }, v.short || v.name, more ? ` +${more}` : "");
    const open = () => ctx.showDetail(s);
    if (dense) {
      return el("button", { type: "button", class: cls, onclick: open }, time,
        el("span", { class: "ag-title" }, s.title), cinema(venues[0], venues.length - 1));
    }
    const n = counts.get(C.fold(s.title)) || 1;
    const facts = C.rowFacts(s).map((f) => [" · ", f === s.format ? el("span", { class: "film-fmt" }, f) : f]);
    return el("button", { type: "button", class: cls, onclick: open }, time,
      el("span", { class: "ag-title" }, s.title, n > 1 ? el("span", { class: "ag-x" }, ` ×${n}`) : null),
      el("span", { class: "ag-meta" }, venues.map((v) => cinema(v)), facts,
        same > 0 ? ` · ×${group.length}` : null,
        s.note ? el("span", { class: "m-tag" }, s.note) : null));
  }

  /** Hour headers (sticky under the top bar) with the rows of each hour. */
  function byHour(ctx, groups, counts, past) {
    const { C, m, t } = ctx;
    const hours = new Map();
    for (const g of groups) {
      const min = C.minutesInDay(g[0].start, ctx.day, m.tzOf(g[0]));
      const h = Math.floor(min / 60);
      if (!hours.has(h)) hours.set(h, { min: h * 60, rows: [] });
      hours.get(h).rows.push(g);
    }
    return [...hours.values()].map(({ min, rows }) => [
      el("div", { class: "ag-hour" + (past ? " past" : "") }, C.hourLabel(min),
        el("span", {}, t("shows", rows.reduce((n, g) => n + g.length, 0)))),
      rows.map((g) => row(ctx, g, counts, past)),
    ]);
  }

  function render(ctx) {
    const { C, m, t, list, now } = ctx;
    if (ctx.day !== lastDay) { showPast = false; lastDay = ctx.day; }
    if (!list.length) return ctx.empty();
    const counts = new Map();
    for (const s of list) counts.set(C.fold(s.title), (counts.get(C.fold(s.title)) || 0) + 1);
    const groups = sameStart(list, C);
    if (!ctx.isToday) return el("div", { class: "ag" }, byHour(ctx, groups, counts, ctx.day < ctx.today));

    const started = groups.filter((g) => new Date(g[0].start) < now);
    const coming = groups.filter((g) => new Date(g[0].start) >= now);
    const nStarted = started.reduce((n, g) => n + g.length, 0);
    const tz = m.tzOf(list[0]);
    return el("div", { class: "ag" + (dense ? " dense" : "") },
      started.length ? el("button", {
        type: "button", class: "ag-fold", "aria-expanded": String(showPast),
        onclick: () => { showPast = !showPast; ctx.refresh(); },
      }, el("span", {}, t("started", nStarted)), el("span", { class: "ag-fold-act" }, showPast ? t("hideStarted") + " ▴" : "▸")) : null,
      showPast ? byHour(ctx, started, counts, true) : null,
      el("div", { class: "ag-now", role: "separator" }, el("span", {}, `${t("now")} ${C.timeLabel(now.toISOString(), tz)}`)),
      coming.length ? byHour(ctx, coming, counts, false) : ctx.empty(t("dayEmpty")));
  }

  window.MChrome.start({
    id: "agenda",
    render,
    tools: (ctx) => el("button", {
      type: "button", class: "m-hbtn", "aria-pressed": String(dense), "aria-label": ctx.t("dense"), title: ctx.t("dense"),
      onclick: () => { dense = !dense; try { localStorage.setItem(KEY, dense ? "1" : "0"); } catch (_) { /* ignore */ } ctx.refresh(); },
    }, el("span", { class: "m-hbtn-in" }, ctx.icon("rows", 18))),
    after(ctx, opts) {
      if (!opts.first || !ctx.state.hl) return;
      const hit = ctx.main.querySelector(".ag-row.hl");
      if (hit) hit.scrollIntoView({ block: "center" });
    },
  });
})();
