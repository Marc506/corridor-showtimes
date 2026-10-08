/* Corridor Showtimes, phone pages — the data layer every demo under site/m/ shares.
 * Pure functions over window.CINEMA_DATA: indexes, filters, grouping, times in each cinema's own time zone,
 * URL hash and localStorage state, i18n. The hash parameters and storage keys are the main page's
 * (site/app.js), so a link or a cinema selection carries over in both directions.
 * Also loaded under Node by core.test.js; nothing here touches the DOM.
 */
(function (root) {
  "use strict";

  const DEFAULT_TZ = "America/New_York";
  const FILM_FORMATS = new Set(["16mm", "35mm", "70mm", "Film"]);   // "Film" = on film, gauge unknown (screenslate)
  const LS = { venues: "cinema.venues", regions: "cinema.regions", lang: "cinema.lang" };

  const DEMOS = [
    { id: "agenda", zh: "时间流", en: "Agenda",
      zhD: "所有影院按开始时间排成一列、按小时分组；已开场的折叠起来", enD: "Every cinema in one column by start time, grouped by hour; started shows fold away" },
    { id: "venues", zh: "影院", en: "Cinemas",
      zhD: "一家影院一张卡，每部片一行，场次时间是可点的按钮；区域和筛选开关就在页面上", enD: "A card per cinema, a row per film, its times as buttons; regions and filter switches right on the page" },
    { id: "guide", zh: "节目表", en: "Guide",
      zhD: "电视节目表式的横向时间轴：一家影院一行，重叠的场次上下叠放", enD: "A TV-guide timeline: a row per cinema, overlapping shows stacked" },
    { id: "films", zh: "影片", en: "Films",
      zhD: "一部片一张卡，列出各影院的时间；可切到 7 天概览", enD: "A card per film with its times at each cinema; or a 7-day overview" },
  ];

  // ---------- i18n (keys shared with app.js keep its names) ----------
  const I18N = {
    zh: {
      never: "从未", justNow: "刚刚", minAgo: (n) => `${n} 分钟前`, hrAgo: (n) => `${n} 小时前`, dayAgo: (n) => `${n} 天前`,
      updated: (r) => `更新于 ${r}`, range: (a, b) => `数据范围 ${a} – ${b}`,
      today: "今天", todaySuffix: "今天", tomorrowSuffix: "明天",
      tickets: "购票", details: "详情", addCal: "加入日历", appleCal: "Apple 日历", googleCal: "Google 日历",
      calSaved: "已下载日历文件，打开它即可加入日历。", calSafari: "加入 Apple 日历要在 Safari 里打开本页再点；Google 日历在这里也能用。",
      onFilm: "胶片", subs: "有字幕", specials: "限定放映", upcoming: "隐藏已开场", search: "搜索片名 / 导演 / 系列",
      selectAll: "全选", clearFilters: "清除筛选", noVenues: "没有选中任何影院。", noData: "还没有数据。",
      dayEmpty: "这一天所选影院没有符合条件的放映。", close: "关闭", minutes: (n) => `${n} 分钟`, runtimeUnknown: "片长未知",
      filmsShows: (f, n) => `${f} 部 · ${n} 场`, stale: (r) => `旧数据 · ${r}`, failed: "抓取失败",
      viaTag: (src) => `这家的主源暂时抓取失败，数据来自 ${src}，可能不全`, regions: "区域", website: "影院官网",
      // phone pages
      filter: "筛选", all: "全部", searchShort: "搜索", clearSearch: "清除搜索", venuesShows: (n, k) => `${n} 家影院 · ${k} 场`, clear: "清空", done: "完成", cinemas: "影院",
      onlyRegion: (r) => `只看 ${r}`, longPress: "点按选中或取消，长按只看这一家", started: (n) => `已开场 ${n} 场`, startedTag: "已开场",
      hideStarted: "收起", now: "现在", seeTomorrow: "看明天", seeDay: (d) => `看 ${d}`, prevDay: "前一天", nextDay: "后一天",
      pickDate: "选择日期", demos: "换个方案", chooser: "全部方案与评测清单", fullSite: "完整版网页", lang: "English",
      onlyFilm: "只看这部", onlyVenue: (n) => `只看 ${n}`, undo: "撤销", nowOnly: (n) => `现在只看 ${n}`,
      otherTimes: "这家今天的其他场次", sameTime: "同一时间也在", address: "地址", alsoScreen: (x) => `同时在 ${x} 放映`,
      dense: "紧凑", roomy: "宽松", dayMode: "当天", weekMode: "7 天", allStarted: (n) => `已全部开场 ${n} 部`,
      shows: (n) => `${n} 场`, inWeek: (n) => `7 天内 ${n} 场`, weekEmpty: "这 7 天所选影院没有符合条件的放映。",
      dateStrip: "日期", bottomBar: "换日与筛选", menu: "方案菜单", shown: (n, all) => `${n}/${all}`,
    },
    en: {
      never: "never", justNow: "just now", minAgo: (n) => `${n} min ago`, hrAgo: (n) => `${n} h ago`, dayAgo: (n) => `${n} days ago`,
      updated: (r) => `Updated ${r}`, range: (a, b) => `Data ${a} – ${b}`,
      today: "Today", todaySuffix: "Today", tomorrowSuffix: "Tomorrow",
      tickets: "Tickets", details: "Details", addCal: "Add to calendar", appleCal: "Apple Calendar", googleCal: "Google Calendar",
      calSaved: "Calendar file downloaded — open it to add the event.", calSafari: "For Apple Calendar, open this page in Safari and add it there; Google Calendar works here too.",
      onFilm: "On film", subs: "Subtitled", specials: "Limited", upcoming: "Hide started", search: "Search title / director / series",
      selectAll: "All", clearFilters: "Clear filters", noVenues: "No cinemas selected.", noData: "No data yet.",
      dayEmpty: "No matching screenings at the selected cinemas on this day.", close: "Close", minutes: (n) => `${n} min`, runtimeUnknown: "runtime unknown",
      filmsShows: (f, n) => `${f} film${f === 1 ? "" : "s"} · ${n} show${n === 1 ? "" : "s"}`, stale: (r) => `Stale · ${r}`, failed: "Fetch failed",
      viaTag: (src) => `This cinema's own site failed; data from ${src}, may be incomplete`, regions: "Regions", website: "Cinema website",
      filter: "Filters", all: "All", searchShort: "Search", clearSearch: "Clear search", venuesShows: (n, k) => `${n} cinema${n === 1 ? "" : "s"} · ${k} show${k === 1 ? "" : "s"}`, clear: "None", done: "Done", cinemas: "Cinemas",
      onlyRegion: (r) => `Only ${r}`, longPress: "Tap to select, press and hold for only that one", started: (n) => `${n} already started`, startedTag: "started",
      hideStarted: "Hide", now: "Now", seeTomorrow: "Tomorrow", seeDay: (d) => `Go to ${d}`, prevDay: "Previous day", nextDay: "Next day",
      pickDate: "Pick a date", demos: "Switch layout", chooser: "All layouts and the test sheet", fullSite: "Full website", lang: "中文",
      onlyFilm: "Only this film", onlyVenue: (n) => `Only ${n}`, undo: "Undo", nowOnly: (n) => `Showing only ${n}`,
      otherTimes: "Other times here today", sameTime: "Same time at", address: "Address", alsoScreen: (x) => `Also on ${x}`,
      dense: "Compact", roomy: "Roomy", dayMode: "Day", weekMode: "7 days", allStarted: (n) => `${n} film${n === 1 ? "" : "s"} already started`,
      shows: (n) => `${n} show${n === 1 ? "" : "s"}`, inWeek: (n) => `${n} in 7 days`, weekEmpty: "No matching screenings at the selected cinemas in these 7 days.",
      dateStrip: "Dates", bottomBar: "Day and filters", menu: "Layouts", shown: (n, all) => `${n}/${all}`,
    },
  };

  function translator(lang) {
    const dict = I18N[lang] || I18N.en;
    return (key, ...args) => { const v = dict[key]; return typeof v === "function" ? v(...args) : v; };
  }

  /** ?lang= in the hash (remembered), then the saved choice, then the browser's language — as app.js. */
  function initialLang(hash, store, navLang) {
    const fromUrl = ((hash || "").match(/[?&]lang=(zh|en)\b/) || [])[1];
    if (fromUrl) { try { store && store.setItem(LS.lang, fromUrl); } catch (_) { /* ignore */ } return fromUrl; }
    try { const saved = store && store.getItem(LS.lang); if (saved === "zh" || saved === "en") return saved; } catch (_) { /* ignore */ }
    return /^zh\b/i.test(navLang || "") ? "zh" : "en";
  }

  // ---------- time (Intl only; one set of formatters per time zone) ----------
  const fmtCache = new Map();
  function fmts(tz) {
    if (!fmtCache.has(tz)) {
      fmtCache.set(tz, {
        dayKey: new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }),
        time: new Intl.DateTimeFormat("en-US", { timeZone: tz, hour: "numeric", minute: "2-digit" }),
        hm: new Intl.DateTimeFormat("en-US", { timeZone: tz, hour: "numeric", minute: "numeric", hourCycle: "h23" }),
      });
    }
    return fmtCache.get(tz);
  }
  const localDayKey = new Intl.DateTimeFormat("en-CA", { year: "numeric", month: "2-digit", day: "2-digit" });
  const DAY_FMT = {
    zhMD: new Intl.DateTimeFormat("zh-CN", { timeZone: "UTC", month: "long", day: "numeric" }),
    zhWD: new Intl.DateTimeFormat("zh-CN", { timeZone: "UTC", weekday: "short" }),
    zhM: new Intl.DateTimeFormat("zh-CN", { timeZone: "UTC", month: "short" }),
    enTitle: new Intl.DateTimeFormat("en-US", { timeZone: "UTC", weekday: "short", month: "short", day: "numeric" }),
    enWD: new Intl.DateTimeFormat("en-US", { timeZone: "UTC", weekday: "short" }),
    enM: new Intl.DateTimeFormat("en-US", { timeZone: "UTC", month: "short" }),
    enMD: new Intl.DateTimeFormat("en-US", { timeZone: "UTC", month: "short", day: "numeric" }),
  };

  /** The viewer's date, YYYY-MM-DD. */
  const todayKey = (now = new Date()) => localDayKey.format(now);
  const dayDate = (key) => new Date(key + "T12:00:00Z");                                   // noon UTC: safe for date math
  const shiftDay = (key, n) => { const d = dayDate(key); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
  const validDay = (s) => /^\d{4}-\d{2}-\d{2}$/.test(s || "") && !isNaN(dayDate(s));
  const daysBetween = (a, b) => Math.round((dayDate(b) - dayDate(a)) / 864e5);

  /** "7:30pm" in the cinema's time zone. */
  const timeLabel = (iso, tz = DEFAULT_TZ) => fmts(tz).time.format(new Date(iso)).replace(/\s/g, "").toLowerCase();
  /** {hm: "7:30", ap: "pm"} — the agenda's time column sets the two apart. */
  function timeParts(iso, tz = DEFAULT_TZ) {
    const m = timeLabel(iso, tz).match(/^(.*?)(am|pm)$/);
    return m ? { hm: m[1], ap: m[2] } : { hm: timeLabel(iso, tz), ap: "" };
  }

  /** Minutes since midnight of `day` in time zone `tz` (beyond 1440 for after-midnight shows). */
  function minutesInDay(iso, day, tz = DEFAULT_TZ) {
    const f = fmts(tz);
    const [h, m] = f.hm.format(new Date(iso)).split(":").map(Number);
    const d = f.dayKey.format(new Date(iso));
    return (h % 24) * 60 + m + (d > day ? 1440 : d < day ? -1440 : 0);
  }

  /** "7 PM" / "12 AM" for a minute of the day. */
  const hourLabel = (min) => { const h = Math.floor(min / 60) % 24; return `${h % 12 || 12} ${h < 12 ? "AM" : "PM"}`; };

  /** Header title: "10月8日 周四" / "Thu, Oct 8". */
  function dayTitle(key, lang) {
    const d = dayDate(key);
    return lang === "zh" ? `${DAY_FMT.zhMD.format(d)} ${DAY_FMT.zhWD.format(d)}` : DAY_FMT.enTitle.format(d);
  }
  /** Short label for buttons: "10/9 周五" / "Fri 10/9" style kept compact: "周五" / "Fri". */
  const weekday = (key, lang) => (lang === "zh" ? DAY_FMT.zhWD : DAY_FMT.enWD).format(dayDate(key));
  const monthShort = (key, lang) => (lang === "zh" ? DAY_FMT.zhM : DAY_FMT.enM).format(dayDate(key));
  const monthDay = (key, lang) => (lang === "zh" ? DAY_FMT.zhMD : DAY_FMT.enMD).format(dayDate(key));

  /** "Today" / "Tomorrow" / "" relative to `today`. */
  function relDay(key, today, t) {
    if (key === today) return t("todaySuffix");
    if (key === shiftDay(today, 1)) return t("tomorrowSuffix");
    return "";
  }

  function relTime(iso, t, now = Date.now()) {
    if (!iso) return t("never");
    const mins = Math.round((now - new Date(iso)) / 60000);
    if (mins < 1) return t("justNow");
    if (mins < 60) return t("minAgo", mins);
    const h = Math.round(mins / 60);
    if (h < 48) return t("hrAgo", h);
    return t("dayAgo", Math.round(h / 24));
  }

  const fold = (s) => (s || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();

  // ---------- indexes ----------
  function model(DATA) {
    const D = DATA || { venues: [], screenings: [], days: {}, generated_at: null };
    const venueById = Object.fromEntries(D.venues.map((v) => [v.id, v]));
    const byId = Object.fromEntries(D.screenings.map((s) => [s.id, s]));
    const active = D.venues.filter((v) => v.status !== "disabled");
    const regionOf = (v) => (v && (v.region || v.city)) || "";
    const regions = [...new Set(active.map(regionOf))];
    const cache = new Map();
    const twins = new Map();
    for (const s of D.screenings) twins.set(twinKey(s), (twins.get(twinKey(s)) || []).concat(s));
    return {
      data: D, venueById, byId, active, regions, regionOf,
      days: Object.keys(D.days).sort(),
      tzOf: (s) => (venueById[s.venue_id] || {}).timezone || DEFAULT_TZ,
      /** Every screening of a day (any cinema, no filters), by start time. */
      forDay(day) {
        if (!cache.has(day)) {
          cache.set(day, (D.days[day] || []).map((id) => byId[id]).filter(Boolean)
            .sort((a, b) => Date.parse(a.start) - Date.parse(b.start) || a.title.localeCompare(b.title)));
        }
        return cache.get(day);
      },
      /** The same film starting together on several screens of one cinema (including s). */
      twinsOf: (s) => twins.get(twinKey(s)) || [s],
    };
  }

  /** A film starting at the same time on two screens (or in two buildings) of one cinema: "twins". */
  const twinKey = (s) => `${s.venue_id}|${s.start}|${fold(s.title)}`;

  // ---------- state <-> URL hash and storage (same parameters and keys as app.js) ----------
  function blankState(m, today) {
    return {
      day: today, view: "", venues: new Set(m.active.map((v) => v.id)), regions: new Set(m.regions),
      film: false, subs: false, upcoming: false, specials: false, q: "", ws: "", hl: "",
    };
  }

  /** Stored as {on: [...], known: [...]} — cinemas added to the site later start selected. */
  function loadVenues(store, m) {
    try {
      const raw = JSON.parse((store && store.getItem(LS.venues)) || "null");
      if (raw) {
        const on = Array.isArray(raw) ? raw : raw.on || [];
        const known = new Set(Array.isArray(raw) ? [] : raw.known || []);
        const ids = m.active.map((v) => v.id).filter((id) => on.includes(id) || !known.has(id));
        if (ids.length) return new Set(ids);
      }
    } catch (_) { /* storage unavailable or corrupt */ }
    return null;
  }
  function saveVenues(store, state, m) {
    try { store && store.setItem(LS.venues, JSON.stringify({ on: [...state.venues], known: m.active.map((v) => v.id) })); } catch (_) { /* ignore */ }
  }
  function loadRegions(store, m) {
    try {
      const raw = JSON.parse((store && store.getItem(LS.regions)) || "null");
      if (Array.isArray(raw)) {
        const on = m.regions.filter((r) => raw.includes(r));
        if (on.length || !raw.length) return new Set(on);     // [] = every region switched off on purpose
      }
    } catch (_) { /* storage unavailable or corrupt */ }
    return null;
  }
  function saveRegions(store, state) {
    try { store && store.setItem(LS.regions, JSON.stringify([...state.regions])); } catch (_) { /* ignore */ }
  }

  /** As app.js readHash: a past date in the URL (a reopened tab, a bookmark) lands on today. */
  function parseHash(hash, m, today, store) {
    const st = blankState(m, today);
    const mt = (hash || "").match(/^#\/([^?]*)(?:\?(.*))?$/);
    const p = new URLSearchParams(mt ? mt[2] || "" : "");
    st.day = mt && validDay(mt[1]) && mt[1] >= today ? mt[1] : today;
    st.view = p.get("view") || "";
    if (p.has("v")) {
      const ids = p.get("v").split(",").filter((id) => m.venueById[id]);
      st.venues = new Set(ids.length ? ids : m.active.map((v) => v.id));
    } else {
      st.venues = loadVenues(store, m) || st.venues;
    }
    if (p.has("r")) {
      const raw = p.get("r");
      const rs = raw.split(",").filter((r) => m.regions.includes(r));
      st.regions = new Set(rs.length || !raw ? rs : m.regions);           // "r=" = none on; unknown names = all
    } else {
      st.regions = loadRegions(store, m) || st.regions;
    }
    st.film = p.get("film") === "1";
    st.subs = p.get("sub") === "1";
    st.upcoming = p.get("up") === "1";
    st.specials = p.get("sp") === "1";
    st.q = p.get("q") || "";
    st.ws = p.get("ws") || "";
    st.hl = p.get("hl") || "";
    return st;
  }

  function buildHash(st, m, today) {
    const p = new URLSearchParams();
    if (st.view && st.view !== "timeline") p.set("view", st.view);
    const all = st.venues.size === m.active.length && m.active.every((v) => st.venues.has(v.id));
    if (!all) p.set("v", [...st.venues].join(","));
    if (st.regions.size < m.regions.length) p.set("r", [...st.regions].join(","));
    if (st.film) p.set("film", "1");
    if (st.subs) p.set("sub", "1");
    if (st.upcoming) p.set("up", "1");
    if (st.specials) p.set("sp", "1");
    if (st.q) p.set("q", st.q);
    if (st.ws) p.set("ws", st.ws);
    if (st.hl) p.set("hl", st.hl);
    const q = p.toString().replace(/%2C/g, ",");
    return `#/${st.day === today ? "" : st.day}${q ? "?" + q : ""}`;
  }

  // ---------- filters (same meaning as app.js passesFilters) ----------
  const isOnFilm = (s) => FILM_FORMATS.has(s.format);
  const shown = (st, m, vid) => st.venues.has(vid) && st.regions.has(m.regionOf(m.venueById[vid]));

  /** true = subtitled / captioned / silent (no English listening needed), false = English, null = unknown. */
  function needsNoEnglish(s) {
    if (/open caption|\bsubtitled\b/i.test(s.note || "")) return true;
    if (!s.language) return null;
    return s.language.split(",")[0].trim().toLowerCase() !== "english";
  }

  function passes(s, st, now = new Date(), today = todayKey(now)) {
    if (st.film && !isOnFilm(s)) return false;
    if (st.subs && needsNoEnglish(s) !== true) return false;
    if (st.upcoming && s.day === today && new Date(s.start) < now) return false;
    if (st.specials && s.run) return false;        // "Limited screenings": hides new films that opened widely
    if (st.q) {
      const q = fold(st.q);
      if (!fold(s.title).includes(q) && !fold(s.director).includes(q) && !fold(s.series).includes(q)) return false;
    }
    return true;
  }

  /** The screenings on screen for a day: selected cinemas in selected regions, every filter applied. */
  function visible(m, st, day, now = new Date(), today = todayKey(now)) {
    return m.forDay(day).filter((s) => shown(st, m, s.venue_id) && passes(s, st, now, today));
  }

  /** Screenings per day for the date strip. */
  function dayCounts(m, st, days, now = new Date(), today = todayKey(now)) {
    return Object.fromEntries(days.map((d) => [d, visible(m, st, d, now, today).length]));
  }

  /** The nearest day before / after `day` with something to show, or null. */
  function nearestDay(m, st, day, dir, now = new Date(), today = todayKey(now)) {
    const list = dir > 0 ? m.days.filter((d) => d > day) : m.days.filter((d) => d < day && d >= today).reverse();
    return list.find((d) => visible(m, st, d, now, today).length) || null;
  }

  // ---------- grouping ----------
  /** As app.js: screenings of the same programme at one cinema in one row (screens don't matter here). */
  function groupFilms(list) {
    const rows = new Map();
    for (const s of list) {
      const key = [s.title, s.series || "", s.note || ""].join("|");
      if (!rows.has(key)) rows.set(key, { ...s, showings: [] });
      rows.get(key).showings.push(s);
    }
    const out = [...rows.values()];
    out.forEach((r) => r.showings.sort((a, b) => a.start.localeCompare(b.start)));
    return out.sort((a, b) => a.showings[0].start.localeCompare(b.showings[0].start) || a.title.localeCompare(b.title));
  }

  /** [[venue_id, screenings]], cinemas in order of their earliest screening (as instants). */
  function groupByVenue(list) {
    const byVenue = new Map();
    for (const s of list) {
      if (!byVenue.has(s.venue_id)) byVenue.set(s.venue_id, []);
      byVenue.get(s.venue_id).push(s);
    }
    const earliest = (l) => l.reduce((acc, s) => Math.min(acc, Date.parse(s.start)), Infinity);
    return [...byVenue.entries()].sort((a, b) => earliest(a[1]) - earliest(b[1]));
  }

  /** Twins collapsed: one entry per (cinema, start, title), each an array of screenings. */
  function groupTwins(list) {
    const rows = new Map();
    for (const s of list) {
      if (!rows.has(twinKey(s))) rows.set(twinKey(s), []);
      rows.get(twinKey(s)).push(s);
    }
    return [...rows.values()];
  }

  const normTitle = (t) => fold(t).replace(/&/g, " and ").replace(/[^\p{L}\p{N}]+/gu, " ").trim();
  const normName = (t) => fold(t).replace(/[^\p{L}\p{N}]+/gu, "");
  const sameDirector = (a, b) => !a || !b || a.includes(b) || b.includes(a);

  /** One film across cinemas: the same title (case, accents and punctuation aside) whose years (±1) and
   *  directors don't contradict each other — a remake or another film of the same name stays apart.
   *  Returns [{key, title, year, director, runtime_min, language, series, showings}], showings by start. */
  function filmClusters(list) {
    const byTitle = new Map();
    const out = [];
    for (const s of list) {
      const k = normTitle(s.title);
      if (!byTitle.has(k)) byTitle.set(k, []);
      const groups = byTitle.get(k);
      const year = s.year || null, dir = normName(s.director) || null;
      let g = groups.find((x) => (!year || !x.year || Math.abs(x.year - year) <= 1) && sameDirector(x.dir, dir));
      if (!g) {
        g = { key: `${k}|${groups.length}`, title: s.title, year, dir, director: s.director || null,
          runtime_min: s.runtime_min || null, language: s.language || null, series: new Set(), showings: [] };
        groups.push(g);
        out.push(g);
      }
      g.year = g.year || year; g.dir = g.dir || dir; g.director = g.director || s.director || null;
      g.runtime_min = g.runtime_min || s.runtime_min || null; g.language = g.language || s.language || null;
      if (s.series) g.series.add(s.series);
      g.showings.push(s);
    }
    for (const g of out) g.showings.sort((a, b) => Date.parse(a.start) - Date.parse(b.start));
    return out;
  }

  /** Greedy lane packing (items carry from / to in minutes); sets item.lane, returns the lane count. */
  function packLanes(items, gap = 3) {
    const lanes = [];
    for (const it of items.sort((a, b) => a.from - b.from || b.to - a.to)) {
      let i = lanes.findIndex((end) => end <= it.from);
      if (i < 0) { i = lanes.length; lanes.push(0); }
      lanes[i] = it.to + gap;
      it.lane = i;
    }
    return Math.max(lanes.length, 1);
  }

  /** Start and end of a screening in minutes of `day` (runtime unknown: drawn as `fallback` minutes). */
  function span(s, day, tz, fallback = 100) {
    const from = minutesInDay(s.start, day, tz);
    const to = s.end ? Math.max(minutesInDay(s.end, day, tz), from + 15) : from + (s.runtime_min || fallback);
    return { from, to, known: !!(s.end || s.runtime_min) };
  }

  /** Short facts for a row: runtime, on-film format, a non-English language. */
  function rowFacts(s) {
    const lang = s.language && s.language.split(",")[0].trim();
    return [s.runtime_min ? `${s.runtime_min}m` : null, isOnFilm(s) ? s.format : null,
      lang && lang.toLowerCase() !== "english" ? lang : null].filter(Boolean);
  }

  const api = {
    DEFAULT_TZ, FILM_FORMATS, LS, DEMOS, I18N, translator, initialLang,
    todayKey, dayDate, shiftDay, validDay, daysBetween, timeLabel, timeParts, minutesInDay, hourLabel,
    dayTitle, weekday, monthShort, monthDay, relDay, relTime, fold,
    model, twinKey, blankState, loadVenues, saveVenues, loadRegions, saveRegions, parseHash, buildHash,
    isOnFilm, shown, needsNoEnglish, passes, visible, dayCounts, nearestDay,
    groupFilms, groupByVenue, groupTwins, normTitle, filmClusters, packLanes, span, rowFacts,
  };
  root.MCore = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
