/* Films (MOBILE.md §4 D) — a card per film across cinemas (same title; years and directors that don't
 * contradict). "Day": that day's times cinema by cinema, the film playing next on top. "7 days": how many
 * screenings each day from the selected day on, and where; tap a day to open it. */
(function () {
  "use strict";
  const { el } = window.MChrome;
  const KEY = "cinema.m.films.week";
  let week = (() => { try { return localStorage.getItem(KEY) === "1"; } catch (_) { return false; } })();
  let showDone = false;
  let lastDay = null;

  const next = (shows, now) => {
    const s = shows.find((x) => new Date(x.start) >= now);
    return s ? Date.parse(s.start) : Infinity;
  };

  function setWeek(ctx, on) {
    week = on;
    try { localStorage.setItem(KEY, on ? "1" : "0"); } catch (_) { /* ignore */ }
    window.scrollTo(0, 0);
    ctx.refresh();
  }

  /** Title, facts, series. A film at one cinema names it first in the facts line (no cinema rows). */
  function head(ctx, f, venue) {
    const lang = f.language && f.language.split(",")[0].trim();
    const meta = [f.director, f.year, f.runtime_min ? `${f.runtime_min}m` : null,
      lang && lang.toLowerCase() !== "english" ? lang : null].filter(Boolean).join(" · ");
    const series = [...f.series];
    return el("div", { class: "fm-head" },
      el("h3", { class: "fm-title" }, f.title),
      venue || meta ? el("div", { class: "fm-sub" },
        venue ? el("span", { class: "fm-at" }, ctx.dot(venue), venue.name) : null, venue && meta ? " · " : "", meta) : null,
      series.length ? el("div", { class: "fm-series" }, series[0], series.length > 1 ? ` +${series.length - 1}` : "") : null);
  }

  function bar(ctx, nFilms, nShows) {
    const { t } = ctx;
    return el("div", { class: "fm-bar" },
      el("span", { class: "fm-sum" }, week ? `${t("weekMode")} · ${t("filmsShows", nFilms, nShows)}` : t("filmsShows", nFilms, nShows)),
      el("div", { class: "fm-seg", role: "group" },
        el("button", { type: "button", "aria-pressed": String(!week), onclick: () => setWeek(ctx, false) }, t("dayMode")),
        el("button", { type: "button", "aria-pressed": String(week), onclick: () => setWeek(ctx, true) }, t("weekMode"))));
  }

  function dayCard(ctx, f) {
    const { C, m, now } = ctx;
    const hl = ctx.state.hl && C.normTitle(ctx.state.hl) === C.normTitle(f.title);
    const cls = "fm-card" + (hl ? " hl" : "");
    const byVenue = C.groupByVenue(f.showings);
    if (byVenue.length === 1) {
      const v = m.venueById[byVenue[0][0]] || {};
      const one = f.showings.length === 1;             // a single time sits beside the title
      return el("article", { class: cls + (one ? " one" : "") }, head(ctx, f, v),
        one ? ctx.timePill(f.showings[0], now) : el("div", { class: "m-times fm-solo" }, f.showings.map((s) => ctx.timePill(s, now))));
    }
    return el("article", { class: cls }, head(ctx, f),
      el("div", { class: "fm-venues" }, byVenue.map(([vid, shows]) => {
        const v = m.venueById[vid] || {};
        return el("div", { class: "fm-v" },
          el("span", { class: "fm-vn" }, ctx.dot(v), el("span", {}, v.name)),
          el("div", { class: "m-times" }, shows.map((s) => ctx.timePill(s, now))));
      })));
  }

  function weekCard(ctx, f, days) {
    const { C, m, t, lang } = ctx;
    const perDay = new Map(), perVenue = new Map();
    for (const s of f.showings) {
      perDay.set(s.day, (perDay.get(s.day) || 0) + 1);
      perVenue.set(s.venue_id, (perVenue.get(s.venue_id) || 0) + 1);
    }
    return el("article", { class: "fm-card" }, head(ctx, f),
      el("div", { class: "fm-week" }, days.map((d) => {
        const n = perDay.get(d) || 0;
        return el("button", {
          type: "button", class: "fm-wd" + (n ? "" : " zero") + (d === ctx.today ? " today" : ""), disabled: !n,
          "aria-label": `${C.dayTitle(d, lang)} · ${t("shows", n)}`,
          onclick: () => { week = false; try { localStorage.setItem(KEY, "0"); } catch (_) { /* ignore */ } ctx.update({ day: d, hl: f.title }, { dayChanged: true }); },
        }, el("span", { class: "wd" }, C.weekday(d, lang)), el("span", { class: "n" }, n || "·"));
      })),
      el("div", { class: "fm-vsum" }, [...perVenue.entries()].sort((a, b) => b[1] - a[1]).map(([vid, n]) => {
        const v = m.venueById[vid] || {};
        return el("span", { class: "fm-vs" }, ctx.dot(v), `${v.short || v.name} `, el("b", {}, n));
      })));
  }

  function render(ctx) {
    const { C, m, t, now, state } = ctx;
    if (ctx.day !== lastDay) { showDone = false; lastDay = ctx.day; }
    if (week) {
      const days = [...Array(7)].map((_, i) => C.shiftDay(ctx.day, i));
      const list = days.flatMap((d) => C.visible(m, state, d, now, ctx.today));
      if (!list.length) return [bar(ctx, 0, 0), ctx.empty(t("weekEmpty"))];
      const films = C.filmClusters(list)
        .sort((a, b) => next(a.showings, now) - next(b.showings, now) || b.showings.length - a.showings.length);
      return [bar(ctx, films.length, list.length), el("div", { class: "fm" }, films.map((f) => weekCard(ctx, f, days)))];
    }
    if (!ctx.list.length) return [bar(ctx, 0, 0), ctx.empty()];
    const films = C.filmClusters(ctx.list)
      .sort((a, b) => next(a.showings, now) - next(b.showings, now) || Date.parse(a.showings[0].start) - Date.parse(b.showings[0].start));
    const coming = films.filter((f) => next(f.showings, now) !== Infinity);
    const done = films.filter((f) => next(f.showings, now) === Infinity);
    const fold = ctx.isToday && done.length > 0;
    return [bar(ctx, films.length, ctx.list.length), el("div", { class: "fm" },
      (fold ? coming : films).map((f) => dayCard(ctx, f)),
      fold ? el("button", { type: "button", class: "fm-fold", "aria-expanded": String(showDone),
        onclick: () => { showDone = !showDone; ctx.refresh(); } },
        el("span", {}, t("allStarted", done.length)), el("span", {}, showDone ? "▴" : "▾")) : null,
      fold && showDone ? done.map((f) => dayCard(ctx, f)) : null)];
  }

  window.MChrome.start({
    id: "films",
    render,
    after(ctx, opts) {
      if (week || !ctx.state.hl || !(opts.first || opts.dayChanged)) return;
      const hit = ctx.main.querySelector(".fm-card.hl");
      if (hit) window.scrollTo(0, hit.getBoundingClientRect().top + window.scrollY - 110);
    },
  });
})();
