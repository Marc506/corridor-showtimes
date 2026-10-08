/* Cinemas (MOBILE.md §4 B) — a card per cinema: region by region, the cinema whose next screening comes
 * first on top. Each film is a row with its start times as pills. Tap a card's name to fold it; press and
 * hold it to show only that cinema. */
(function () {
  "use strict";
  const { el, icon } = window.MChrome;
  const KEY = "cinema.m.venues.folded";
  const folded = new Set((() => { try { return JSON.parse(localStorage.getItem(KEY) || "[]"); } catch (_) { return []; } })());
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify([...folded])); } catch (_) { /* ignore */ } };

  /** The start of the next screening that hasn't begun (Infinity when all have). */
  const next = (list, now) => {
    const s = list.find((x) => new Date(x.start) >= now);
    return s ? Date.parse(s.start) : Infinity;
  };

  function filmRow(ctx, f) {
    const { C, now } = ctx;
    const lang = f.language && f.language.split(",")[0].trim();
    const meta = [f.director, f.year, f.runtime_min ? `${f.runtime_min}m` : null,
      lang && lang.toLowerCase() !== "english" ? lang : null].filter(Boolean).join(" · ");
    const done = f.showings.every((s) => new Date(s.start) < now);
    const hl = ctx.state.hl && C.fold(ctx.state.hl) === C.fold(f.title);
    const one = f.showings.length === 1;               // a single time sits beside the title, not under it
    return el("div", { class: "vn-film" + (one ? " one" : "") + (done ? " done" : "") + (hl ? " hl" : "") },
      el("div", { class: "vn-text" },
        el("div", { class: "vn-title" }, f.title),
        meta ? el("div", { class: "vn-sub" }, meta) : null,
        f.series || f.note ? el("div", { class: "vn-tags" },
          f.series ? el("span", { class: "vn-series" }, f.series) : null,
          f.note ? el("span", { class: "m-tag" }, f.note) : null) : null),
      one ? ctx.timePill(f.showings[0], now) : el("div", { class: "m-times" }, f.showings.map((s) => ctx.timePill(s, now))));
  }

  function card(ctx, v, list) {
    const { C, t, now } = ctx;
    const films = C.groupFilms(list)
      .sort((a, b) => next(a.showings, now) - next(b.showings, now) || Date.parse(a.showings[0].start) - Date.parse(b.showings[0].start));
    const closed = folded.has(v.id);
    const head = el("button", {
      type: "button", class: "vn-head", "aria-expanded": String(!closed),
      onclick: () => { closed ? folded.delete(v.id) : folded.add(v.id); save(); ctx.refresh(); },
    },
      el("span", { class: "vn-name" }, v.name),
      el("span", { class: "vn-meta" }, t("filmsShows", films.length, list.length)),
      ctx.venueBadge(v),
      icon("down", 18));
    ctx.longPress(head, () => ctx.onlyVenue(v));
    return el("section", { class: "vn-card" + (closed ? " closed" : ""), style: `--c:${v.color}` },
      head, closed ? null : el("div", { class: "vn-films" }, films.map((f) => filmRow(ctx, f))));
  }

  function render(ctx) {
    const { C, m, t, list, now } = ctx;
    if (!list.length) return ctx.empty();
    const byVenue = C.groupByVenue(list);
    const out = [];
    for (const r of m.regions) {
      const rows = byVenue.filter(([vid]) => m.regionOf(m.venueById[vid]) === r)
        .sort((a, b) => next(a[1], now) - next(b[1], now) || Date.parse(a[1][0].start) - Date.parse(b[1][0].start));
      if (!rows.length) continue;
      if (m.regions.length > 1) {
        out.push(el("h2", { class: "vn-region" }, r, el("span", {}, t("shows", rows.reduce((n, [, l]) => n + l.length, 0)))));
      }
      out.push(rows.map(([vid, l]) => card(ctx, m.venueById[vid], l)));
    }
    return el("div", { class: "vn" }, out);
  }

  window.MChrome.start({
    id: "venues",
    render,
    after(ctx, opts) {
      if (!opts.first || !ctx.state.hl) return;
      const hit = ctx.main.querySelector(".vn-film.hl");
      if (hit) hit.scrollIntoView({ block: "center" });
    },
  });
})();
