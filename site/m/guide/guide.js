/* Guide (MOBILE.md §4 C) — a TV-guide timeline: hours run across (160px an hour) under a sticky time axis,
 * a row per cinema whose name sticks to the left (84px: full names, three lines at most); overlapping
 * screenings of one cinema stack as 48px
 * sub-rows instead of squeezing side by side. One scroller, sticky positioning only (no scroll syncing).
 * Opens at "now − 30 min" (today) or just before the first screening. */
(function () {
  "use strict";
  const { el } = window.MChrome;
  const HOUR = 160, PPM = HOUR / 60, LABEL_W = 84, LANE_H = 48, HEAD_H = 28, NARROW = 90;
  let box = null;
  let geo = null;              // {t0, t1, day} of the drawing on screen
  let saved = null;            // scroll position to restore after a re-render of the same day

  const x = (min) => (min - geo.t0) * PPM;
  /** An hour label the red "now" tag would cover (the tag spans about ±11 minutes). */
  const near = (h, nm) => nm != null && nm > h - 12 && nm < h + 28;

  function nowMinute(ctx) {
    if (!ctx.isToday || !ctx.list.length) return null;
    return ctx.C.minutesInDay(ctx.now.toISOString(), ctx.day, ctx.m.tzOf(ctx.list[0]));
  }

  function render(ctx) {
    const { C, m, t, list, now, day } = ctx;
    if (!list.length) { box = null; return ctx.empty(); }
    const items = list.map((s) => ({ s, ...C.span(s, day, m.tzOf(s)) }));
    const t0 = Math.min(600, Math.floor(Math.min(...items.map((i) => i.from)) / 60) * 60);
    const t1 = Math.max(1440, Math.ceil(Math.max(...items.map((i) => i.to)) / 60) * 60);
    geo = { t0, t1, day };
    const width = x(t1);

    const hours = [];
    const nm = nowMinute(ctx);
    for (let h = t0; h < t1; h += 60) hours.push(el("span", { class: "gd-hour" + (near(h, nm) ? " near" : ""), "data-min": h, style: `left:${x(h)}px` }, C.hourLabel(h)));
    const showNow = nm != null && nm >= t0 && nm <= t1;

    const rows = C.groupByVenue(list).map(([vid]) => {
      const v = m.venueById[vid] || {};
      const vi = items.filter((i) => i.s.venue_id === vid);
      const lanes = C.packLanes(vi);
      const blocks = vi.map(({ s, from, to, known, lane }) => {
        const w = Math.max((to - from) * PPM - 3, 24);
        const past = new Date(s.start) < now;
        const hl = ctx.state.hl && C.fold(ctx.state.hl) === C.fold(s.title);
        const cls = ["gd-b", past && "past", !known && "unknown", hl && "hl", w < NARROW && "narrow"].filter(Boolean).join(" ");
        return el("button", {
          type: "button", class: cls, style: `left:${x(from)}px;top:${lane * LANE_H + 2}px;width:${w}px`,
          "aria-label": `${C.timeLabel(s.start, m.tzOf(s))} ${s.title} · ${v.short || v.name}`, onclick: () => ctx.showDetail(s),
        },
          el("span", { class: "gd-t" }, C.timeLabel(s.start, m.tzOf(s)), C.isOnFilm(s) ? el("em", {}, ` ${s.format}`) : null),
          w >= NARROW ? el("span", { class: "gd-n" }, s.title) : null);
      });
      return el("div", { class: "gd-row", style: `--c:${v.color};height:${lanes * LANE_H + 2}px` },
        el("div", { class: "gd-label" },
          el("span", { class: "gd-vn" }, v.name), ctx.venueBadge(v) ? el("span", { class: `gd-warn ${v.status}`, "aria-hidden": "true" }) : null),
        el("div", { class: "gd-track", style: `width:${width}px` }, blocks));
    });

    box = el("div", { class: "gd", "data-noswipe": "" },
      el("div", { class: "gd-inner", style: `width:${LABEL_W + width}px;--label-w:${LABEL_W}px;--hour:${HOUR}px` },
        el("div", { class: "gd-head" },
          el("div", { class: "gd-corner" }, C.monthDay(day, ctx.lang)),
          el("div", { class: "gd-axis", style: `width:${width}px` }, hours,
            showNow ? el("span", { class: "gd-now-tag", style: `left:${x(nm)}px` }, C.timeLabel(now.toISOString(), m.tzOf(list[0]))) : null)),
        el("div", { class: "gd-body" }, rows,
          showNow ? el("div", { class: "gd-now", style: `left:${LABEL_W + x(nm)}px` }) : null)));
    box.addEventListener("scroll", () => { saved = { day, left: box.scrollLeft, top: box.scrollTop }; }, { passive: true });
    return box;
  }

  /** Scroll so minute `min` sits just right of the cinema names. */
  function scrollToMinute(min) {
    if (box && geo) box.scrollLeft = Math.max(0, x(min));
  }

  function focusMinute(ctx) {
    const nm = nowMinute(ctx);
    if (nm != null) return nm - 30;
    return Math.min(...ctx.list.map((s) => ctx.C.minutesInDay(s.start, ctx.day, ctx.m.tzOf(s)))) - 30;
  }

  window.MChrome.start({
    id: "guide",
    swipe: false,                  // sideways scrolling is the timeline's own; days change from the bars
    render,
    extra: {
      label: (t) => t("now"),
      onClick(ctx) {
        if (!ctx.isToday) return ctx.go(ctx.today);
        if (box && geo) box.scrollTo({ left: Math.max(0, x(focusMinute(ctx))), top: 0, behavior: "smooth" });   // one call: a second smooth scroll would cancel the first
      },
    },
    after(ctx, opts) {
      if (!box) return;
      if (saved && saved.day === ctx.day && !opts.dayChanged && !opts.first) {
        box.scrollLeft = saved.left;
        box.scrollTop = saved.top;
        return;
      }
      if (ctx.state.hl) {
        const hit = box.querySelector(".gd-b.hl");
        if (hit) {
          box.scrollLeft = Math.max(0, hit.offsetLeft - 20);
          box.scrollTop = Math.max(0, hit.closest(".gd-row").offsetTop - HEAD_H - 40);
          return;
        }
      }
      scrollToMinute(focusMinute(ctx));
      saved = { day: ctx.day, left: box.scrollLeft, top: box.scrollTop };
    },
    tick(ctx) {                    // move the "now" line without redrawing
      if (!box || !geo || geo.day !== ctx.day) return;
      const nm = nowMinute(ctx);
      const line = box.querySelector(".gd-now"), tag = box.querySelector(".gd-now-tag");
      if (nm == null || !line) return;
      line.style.left = `${LABEL_W + x(nm)}px`;
      box.querySelectorAll(".gd-hour").forEach((e) => e.classList.toggle("near", near(+e.dataset.min, nm)));
      if (tag) {
        tag.style.left = `${x(nm)}px`;
        tag.textContent = ctx.C.timeLabel(ctx.now.toISOString(), ctx.m.tzOf(ctx.list[0]));
      }
    },
  });
})();
