/* Corridor Showtimes — the planner (排片, PLANNER.md). A button beside the view switch (main page) or at the
 * head of the filter row (phone page) opens one panel in three steps: the range (days, cinemas, filters), the films, and up to
 * three plans with one screening per film, none overlapping. A plan goes to the calendar as one .ics file, or
 * to someone else as a link (index.html?plan=…, which opens straight on the plans).
 *
 * Self-contained: reads window.CINEMA_DATA, the URL hash and the page's localStorage keys, never calls into
 * app.js or the phone shell; solves in a Web Worker built from plan.js; uses calendar.js for the .ics.
 * Its own state is kept in localStorage "cinema.plan".
 */
(function () {
  "use strict";

  const P = window.CinemaPlan;
  const CAL = window.CinemaCalendar;
  const DATA = window.CINEMA_DATA;
  if (!P || !DATA || !document.body) return;

  const LS_PLAN = "cinema.plan";
  const LS_VENUES = "cinema.venues";
  const LS_REGIONS = "cinema.regions";
  const EXACT_FILMS = 12;
  const store = (() => { try { return window.localStorage; } catch (_) { return null; } })();

  // ---------- i18n ----------
  const I18N = {
    zh: {
      plan: "排片", planT: "选几部想看的片，排出互不冲突的观影方案", close: "关闭",
      steps: ["范围", "选片", "方案"],
      dates: "日期", today: "今天", tomorrow: "明天", weekend: "本周末", d7: "未来 7 天", d14: "未来 14 天", custom: "自定义", to: "至",
      cinemas: "影院", selectAll: "全选", clear: "清空", filters: "筛选",
      onFilm: "只看胶片", subs: "有字幕", specials: "限定放映",
      more: "更多条件", window: "每天的时间", earliest: "最早开场", latest: "最晚散场", perDay: "每天最多",
      perDayN: (n) => `${n} 场`, noLimit: "不限", allowTight: "允许紧张换场（换场少于 15 分钟）",
      miss: "允许错过片头 / 片尾", missN: (n) => `至多 ${n} 分钟`, missOff: "不允许",
      scopeCount: (f, n) => `范围内 ${f} 部影片 · ${n} 场`, toFilms: "下一步：选片", back: "返回",
      search: "搜索片名、导演或影院", sortBy: "排序", sortTitle: "片名", sortCount: "场次数", sortFirst: "最早场次",
      picked: (k) => `已选 ${k} 部`, go: "开始排片", approxWarn: "超过 12 部将使用近似算法",
      maxPick: (n) => `最多选 ${n} 部`, clearPicked: "清空", notInScope: "范围内没有场次",
      filmLine: (n, where) => `${n} 场 · ${where}`, nVenues: (n) => `${n} 家影院`, minutes: (n) => `${n} 分钟`,
      noFilms: "这个范围里没有符合条件的放映，换个日期或影院试试。", noMatch: (q) => `没有和「${q}」匹配的影片。`,
      solving: "正在排片…", solvingOverlap: "正在找允许错过片头 / 片尾的方案…",
      planN: (i) => `方案 ${i}`,
      obj: { relaxed: "宽松", compact: "紧凑", early: "早场", overlap: "错过片头/片尾", drop: "舍弃替代" },
      objT: { relaxed: "换场最从容", compact: "用的天数最少", early: "每天散场最早", overlap: "相邻两场允许重叠几分钟", drop: "改为舍弃另一部" },
      alsoObj: (l) => `（也是${l.join("、")}方案）`,
      statFilms: (a, b) => `${a}/${b} 部`, statDays: (n) => `${n} 天`, statMinGap: (n) => `最短间隔 ${n} 分钟`,
      statTight: (n) => `${n} 处紧张`, statOverlap: (m, n) => `重叠 ${m} 分钟 · ${n} 处`, statLastEnd: (t) => `最晚 ${t} 散场`,
      badgeDrop: (n) => `舍弃 ${n} 部`, badgeOverlap: (m) => `错过 ${m} 分钟`,
      importCal: "导入日历", expand: "展开", collapse: "收起", share: "分享",
      gapT: (n) => `换场 ${n} 分钟`, tightT: (n) => `换场只有 ${n} 分钟（紧张）`, overlapT: (n) => `两场重叠 ${n} 分钟`,
      missLine: (a, b, m) => `错过 ${a} 片尾 ${m} 分钟，或 ${b} 片头 ${m} 分钟`,
      unknownRt: "片长未知，按 2 小时计",
      uncovered: "排不进：",
      why: {
        none: "范围内没有场次", excluded: "能看的场次都被排除了", limit: "受每天场数限制",
        only: (when, w) => `范围内只有 ${when} 一场，与 ${w} 冲突`, many: (n, w) => `${n} 场都与 ${w} 冲突`,
      },
      orDrop: "也可以改为舍弃：", altEasy: "其余从容", altTight: (n) => `${n} 处紧张`, altGain: (t) => `换 ${t}`,
      altTitle: (l) => `替代方案 · 舍弃 ${l}`,
      tickets: "购票", details: "详情", google: "Google 日历",
      lock: "锁定", unlock: "取消锁定", lockedTag: "已锁定", exclude: "排除", swap: "换一场",
      swapAdjusted: "这部片没有和其余场次都不冲突的别的场次，其余场次也作了调整。",
      swapNone: (t) => `${t} 在范围内没有别的场次了。`,
      approx: { size: "影片较多，以下为近似结果。", timeout: "计算超过 2 秒，以下为近似结果。" },
      lockConflict: "锁定的场次之间有冲突，排不出方案。", unlockAll: "取消全部锁定",
      adjustments: (l, x) => [l ? `已锁定 ${l} 场` : null, x ? `已排除 ${x} 场` : null].filter(Boolean).join(" · "),
      resetAdj: "全部恢复", nothing: "一部都排不进。", pickFirst: "先在第 2 步选几部片。",
      sharedNote: "这是分享来的方案：场次已锁定，可以在「展开」里取消锁定，或回到第 1、2 步修改。",
      linkCopied: "链接已复制", copyThis: "复制这个链接：", calSaved: "已下载日历文件，打开它即可加入日历。",
      calSafari: "加入 Apple 日历要在 Safari 里打开本页再点；也可以展开后用每一场的 Google 日历链接。",
      error: "排片出错了：",
    },
    en: {
      plan: "Plan", planT: "Pick the films you want to see and get schedules where nothing clashes", close: "Close",
      steps: ["Range", "Films", "Plans"],
      dates: "Dates", today: "Today", tomorrow: "Tomorrow", weekend: "This weekend", d7: "Next 7 days", d14: "Next 14 days", custom: "Custom", to: "to",
      cinemas: "Cinemas", selectAll: "All", clear: "None", filters: "Filters",
      onFilm: "On film", subs: "Subtitled / captioned", specials: "Limited screenings",
      more: "More options", window: "Hours each day", earliest: "Earliest start", latest: "Latest end", perDay: "At most",
      perDayN: (n) => `${n} a day`, noLimit: "no limit", allowTight: "Allow tight changes (under 15 minutes)",
      miss: "Allow missing a head or tail", missN: (n) => `up to ${n} min`, missOff: "never",
      scopeCount: (f, n) => `${f} film${f === 1 ? "" : "s"} · ${n} show${n === 1 ? "" : "s"} in range`, toFilms: "Next: films", back: "Back",
      search: "Search title, director or cinema", sortBy: "Sort", sortTitle: "Title", sortCount: "Most shows", sortFirst: "Earliest",
      picked: (k) => `${k} picked`, go: "Make plans", approxWarn: "More than 12 films: plans will be approximate",
      maxPick: (n) => `At most ${n} films`, clearPicked: "Clear", notInScope: "No screening in range",
      filmLine: (n, where) => `${n} show${n === 1 ? "" : "s"} · ${where}`, nVenues: (n) => `${n} cinemas`, minutes: (n) => `${n} min`,
      noFilms: "Nothing matches in this range — try other days or cinemas.", noMatch: (q) => `No film matches “${q}”.`,
      solving: "Making plans…", solvingOverlap: "Looking for a plan that misses a few minutes…",
      planN: (i) => `Plan ${i}`,
      obj: { relaxed: "Relaxed", compact: "Fewest days", early: "Early nights", overlap: "Miss a few minutes", drop: "Swap a film" },
      objT: { relaxed: "The most comfortable changes", compact: "Uses the fewest days", early: "Ends earliest each day",
        overlap: "Adjacent shows may overlap by a few minutes", drop: "Gives up another film instead" },
      alsoObj: (l) => ` (also ${l.join(", ")})`,
      statFilms: (a, b) => `${a}/${b} films`, statDays: (n) => `${n} day${n === 1 ? "" : "s"}`, statMinGap: (n) => `shortest gap ${n} min`,
      statTight: (n) => `${n} tight`, statOverlap: (m, n) => `${m} min overlap · ${n}×`, statLastEnd: (t) => `done by ${t}`,
      badgeDrop: (n) => `${n} dropped`, badgeOverlap: (m) => `miss ${m} min`,
      importCal: "Add to calendar", expand: "Details", collapse: "Less", share: "Share",
      gapT: (n) => `${n} min between`, tightT: (n) => `Only ${n} min between (tight)`, overlapT: (n) => `The two overlap by ${n} min`,
      missLine: (a, b, m) => `Miss the last ${m} min of ${a}, or the first ${m} min of ${b}`,
      unknownRt: "Runtime unknown; counted as 2 hours",
      uncovered: "Doesn't fit: ",
      why: {
        none: "no screening in range", excluded: "every screening you could see is excluded", limit: "over the daily limit",
        only: (when, w) => `its only screening, ${when}, clashes with ${w}`, many: (n, w) => `all ${n} screenings clash with ${w}`,
      },
      orDrop: "Or drop instead: ", altEasy: "the rest comfortable", altTight: (n) => `${n} tight`, altGain: (t) => `for ${t}`,
      altTitle: (l) => `Alternative · drop ${l}`,
      tickets: "Tickets", details: "Details", google: "Google Calendar",
      lock: "Lock", unlock: "Unlock", lockedTag: "locked", exclude: "Exclude", swap: "Another showing",
      swapAdjusted: "No other screening of this film fits around the rest, so the others moved too.",
      swapNone: (t) => `${t} has no other screening in range.`,
      approx: { size: "Many films: these plans are approximate.", timeout: "Took over 2 seconds: these plans are approximate." },
      lockConflict: "The locked screenings clash with each other — no plan keeps them all.", unlockAll: "Unlock all",
      adjustments: (l, x) => [l ? `${l} locked` : null, x ? `${x} excluded` : null].filter(Boolean).join(" · "),
      resetAdj: "Reset", nothing: "None of the films fit.", pickFirst: "Pick some films in step 2 first.",
      sharedNote: "A shared plan: its screenings are locked. Unlock them under Details, or change steps 1 and 2.",
      linkCopied: "Link copied", copyThis: "Copy this link:", calSaved: "Calendar file downloaded — open it to add the screenings.",
      calSafari: "For Apple Calendar, open this page in Safari; or use each screening's Google Calendar link under Details.",
      error: "Something went wrong: ",
    },
  };
  const lang = () => (/^zh/i.test(document.documentElement.lang || "") ? "zh" : "en");
  const t = (key, ...args) => { const v = I18N[lang()][key]; return typeof v === "function" ? v(...args) : v; };

  // ---------- data ----------
  const venues = DATA.venues.filter((v) => v.status !== "disabled");
  const venueById = Object.fromEntries(DATA.venues.map((v) => [v.id, v]));
  const regionOf = (v) => (v && (v.region || v.city)) || "";
  const REGIONS = [...new Set(venues.map(regionOf))];
  const dataDays = Object.keys(DATA.days || {}).sort();
  let KEYS = null;                    // screening id → film key, over all data (computed on first open)
  let TITLES = null;                  // film key → title
  function keys() {
    if (!KEYS) {
      KEYS = P.filmKeys(DATA.screenings);
      TITLES = new Map();
      for (const s of DATA.screenings) if (!TITLES.has(KEYS.get(s.id))) TITLES.set(KEYS.get(s.id), s.title);
    }
    return KEYS;
  }
  const titleOf = (key) => (keys(), TITLES.get(key)) || key.replace(/^[it]:/, "");

  // ---------- dates and times ----------
  const localDay = new Intl.DateTimeFormat("en-CA", { year: "numeric", month: "2-digit", day: "2-digit" });
  const todayKey = () => localDay.format(new Date());
  const dayDate = (key) => new Date(key + "T12:00:00Z");
  const shiftDay = (key, n) => { const d = dayDate(key); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
  const validDay = (s) => /^\d{4}-\d{2}-\d{2}$/.test(s || "") && !isNaN(dayDate(s));
  const wdFmt = { zh: new Intl.DateTimeFormat("zh-CN", { timeZone: "UTC", weekday: "short" }), en: new Intl.DateTimeFormat("en-US", { timeZone: "UTC", weekday: "short" }) };
  const weekday = (key) => wdFmt[lang()].format(dayDate(key));
  const dayLabel = (key) => `${weekday(key)} ${+key.slice(5, 7)}/${+key.slice(8)}`;
  const tfCache = new Map();
  const timeLabel = (ms, tz) => {
    const z = tz || "America/New_York";
    if (!tfCache.has(z)) tfCache.set(z, new Intl.DateTimeFormat("en-US", { timeZone: z, hour: "numeric", minute: "2-digit" }));
    return tfCache.get(z).format(ms).replace(/\s/g, "").toLowerCase();
  };
  /** Minutes after midnight (maybe past 24h) → "11:40pm". */
  const clockLabel = (min) => {
    const h = Math.floor(min / 60) % 24, m = ((min % 60) + 60) % 60;
    return `${h % 12 || 12}:${String(m).padStart(2, "0")}${h < 12 ? "am" : "pm"}`;
  };

  function presetRange(preset, today) {
    if (preset === "today") return [today, today];
    if (preset === "tomorrow") { const d = shiftDay(today, 1); return [d, d]; }
    if (preset === "weekend") {
      const dow = dayDate(today).getUTCDay();             // 0 = Sunday … 6 = Saturday
      if (dow === 0) return [today, today];
      const sat = shiftDay(today, 6 - dow);
      return [sat, shiftDay(sat, 1)];
    }
    if (preset === "14d") return [today, shiftDay(today, 13)];
    return [today, shiftDay(today, 6)];
  }
  const PRESETS = [["today", "today"], ["tomorrow", "tomorrow"], ["weekend", "weekend"], ["7d", "d7"], ["14d", "d14"]];

  // ---------- the page's own choices (as app.js / core.js read them) ----------
  function pageScope() {
    const m = location.hash.match(/^#\/([^?]*)(?:\?(.*))?$/);
    const p = new URLSearchParams(m ? m[2] || "" : "");
    const all = venues.map((v) => v.id);
    let on = null;
    if (p.has("v")) {
      const ids = p.get("v").split(",").filter((id) => venueById[id]);
      on = ids.length ? ids : all;
    } else {
      try {
        const raw = JSON.parse((store && store.getItem(LS_VENUES)) || "null");
        if (raw) {
          const list = Array.isArray(raw) ? raw : raw.on || [];
          const known = new Set(Array.isArray(raw) ? [] : raw.known || []);
          const ids = all.filter((id) => list.includes(id) || !known.has(id));
          if (ids.length) on = ids;
        }
      } catch (_) { /* storage unavailable or corrupt */ }
    }
    let regions = null;
    if (p.has("r")) {
      const raw = p.get("r");
      const rs = raw.split(",").filter((r) => REGIONS.includes(r));
      regions = rs.length || !raw ? rs : REGIONS;
    } else {
      try {
        const raw = JSON.parse((store && store.getItem(LS_REGIONS)) || "null");
        if (Array.isArray(raw)) { const rs = REGIONS.filter((r) => raw.includes(r)); if (rs.length || !raw.length) regions = rs; }
      } catch (_) { /* ignore */ }
    }
    const rset = new Set(regions || REGIONS);
    const shown = (on || all).filter((id) => rset.has(regionOf(venueById[id])));
    return { venues: shown.length ? shown : all, film: p.get("film") === "1", subs: p.get("sub") === "1", specials: p.get("sp") === "1" };
  }

  // ---------- state ----------
  const S = {
    step: 1, preset: "7d", from: null, to: null, venues: new Set(), film: false, subs: false, specials: false,
    win: { on: false, earliest: "11:00", latest: "23:59" }, maxPerDay: null, forbidTight: false, maxOverlap: P.DEFAULTS.maxOverlap,
    picked: [], q: "", sort: "title", locked: new Set(), excluded: new Set(),
    result: null, overlap: undefined, running: false, error: null, note: null, alt: null, expanded: new Set(), shared: false,
  };

  function save() {
    try {
      store && store.setItem(LS_PLAN, JSON.stringify({
        preset: S.preset, from: S.from, to: S.to, win: S.win, maxPerDay: S.maxPerDay, forbidTight: S.forbidTight,
        maxOverlap: S.maxOverlap, picked: S.picked, sort: S.sort, locked: [...S.locked], excluded: [...S.excluded],
      }));
    } catch (_) { /* ignore */ }
  }

  function restore() {
    let o = null;
    try { o = JSON.parse((store && store.getItem(LS_PLAN)) || "null"); } catch (_) { /* ignore */ }
    const today = todayKey();
    if (o && typeof o === "object") {
      if (PRESETS.some(([p]) => p === o.preset)) S.preset = o.preset;
      if (o.preset === "custom" && validDay(o.from) && validDay(o.to) && o.from >= today) { S.preset = "custom"; S.from = o.from; S.to = o.to; }
      if (o.win && typeof o.win === "object") S.win = { on: !!o.win.on, earliest: o.win.earliest || "11:00", latest: o.win.latest || "23:59" };
      S.maxPerDay = o.maxPerDay > 0 ? o.maxPerDay : null;
      S.forbidTight = !!o.forbidTight;
      if (o.maxOverlap != null) S.maxOverlap = Math.max(0, Math.min(30, +o.maxOverlap || 0));
      if (Array.isArray(o.picked)) S.picked = o.picked.filter((k) => typeof k === "string");
      if (["title", "count", "first"].includes(o.sort)) S.sort = o.sort;
      if (Array.isArray(o.locked)) S.locked = new Set(o.locked);
      if (Array.isArray(o.excluded)) S.excluded = new Set(o.excluded);
    }
    if (S.preset !== "custom") [S.from, S.to] = presetRange(S.preset, today);
    const page = pageScope();
    S.venues = new Set(page.venues);
    S.film = page.film; S.subs = page.subs; S.specials = page.specials;
    // picked films that no longer have any screening from today on are dropped
    keys();
    const live = new Set(DATA.screenings.filter((s) => s.day >= today).map((s) => KEYS.get(s.id)));
    S.picked = S.picked.filter((k) => live.has(k));
  }

  /** ?plan=… (a shared link) → state; true when it was one. */
  function fromLink() {
    const m = location.search.match(/[?&]plan=([A-Za-z0-9_-]+)/);
    if (!m) return false;
    keys();
    const ids = new Map();
    for (const k of new Set(KEYS.values())) ids.set(P.filmId(k), k);
    const o = P.fromShare(P.decode(m[1]), ids);
    // the link has done its job: a reload shouldn't reopen it
    const rest = location.search.replace(/([?&])plan=[^&]*&?/, "$1").replace(/[?&]$/, "");
    history.replaceState(history.state, "", location.pathname + rest + location.hash);
    if (!o) return false;
    const today = todayKey();
    S.preset = "custom";
    S.from = o.from < today ? today : o.from;
    S.to = o.to < S.from ? S.from : o.to;
    if (o.venues) { const vs = o.venues.filter((id) => venueById[id]); if (vs.length) S.venues = new Set(vs); }
    S.film = o.film; S.subs = o.subs; S.specials = o.specials;
    S.win = o.dayWindow ? { on: true, earliest: o.dayWindow.earliest, latest: o.dayWindow.latest } : { on: false, earliest: "11:00", latest: "23:59" };
    S.maxPerDay = o.maxPerDay; S.forbidTight = o.forbidTight; S.maxOverlap = o.maxOverlap;
    S.picked = o.films; S.locked = new Set(o.locked); S.excluded = new Set(o.excluded);
    S.shared = S.locked.size > 0;
    return S.picked.length > 0;
  }

  function scope(now = Date.now()) {
    return {
      from: S.from, to: S.to, venues: [...S.venues], film: S.film, subs: S.subs, specials: S.specials, now,
      dayWindow: S.win.on ? { earliest: S.win.earliest, latest: S.win.latest } : null,
    };
  }
  const solverOpts = () => ({ maxPerDay: S.maxPerDay, forbidTight: S.forbidTight, maxOverlap: S.maxOverlap,
    locked: [...S.locked], excluded: [...S.excluded] });

  let candCache = null;
  function cands() {
    const key = JSON.stringify(scope(0)) + "|" + Math.floor(Date.now() / 60e3);
    if (!candCache || candCache.key !== key) {
      const list = P.candidates(DATA, keys(), scope());
      candCache = { key, list, films: P.groupFilms(list) };
    }
    return candCache;
  }

  // ---------- solving (a Web Worker built from plan.js; on the page itself when that fails) ----------
  let worker = null, workerUrl = null, jobId = 0, pending = null;
  function getWorker() {
    if (worker === false) return null;
    if (worker) return worker;
    try {
      workerUrl = workerUrl || URL.createObjectURL(new Blob([P.workerSource()], { type: "text/javascript" }));
      worker = new Worker(workerUrl);
      worker.onmessage = (e) => onSolved(e.data);
      worker.onerror = (e) => {
        if (e && e.preventDefault) e.preventDefault();
        try { worker.terminate(); } catch (_) { /* ignore */ }
        worker = false;
        if (pending) solveHere(pending);
      };
    } catch (_) {
      worker = false;
    }
    return worker || null;
  }

  function solveHere(job) {
    setTimeout(() => {
      let main, swap = null, opts = job.opts;
      try {
        if (job.swap) {
          const r = P.swap(job.showings, job.films, job.opts, job.swap.legs, job.swap.leg);
          main = r.result; opts = r.opts; swap = { opts: r.opts, adjusted: r.adjusted };
        } else main = P.plan(job.showings, job.films, job.opts);
      } catch (err) {
        return onSolved({ id: job.id, phase: "error", error: String(err) });
      }
      onSolved({ id: job.id, phase: "main", result: main, swap });
      setTimeout(() => {
        if (job.id !== jobId) return;
        let ov = null;
        try { ov = main.needFallback ? P.planOverlap(job.showings, job.films, opts, main.maxFilms) : null; } catch (_) { /* ignore */ }
        onSolved({ id: job.id, phase: "overlap", result: ov });
      }, 20);
    }, 20);
  }

  function solve(swap = null) {
    if (!S.picked.length) { S.result = null; S.running = false; return render(); }
    // locks and exclusions only matter for the films picked now
    const picked = new Set(S.picked);
    const keep = (id) => picked.has(keys().get(id));
    S.locked = new Set([...S.locked].filter(keep));
    S.excluded = new Set([...S.excluded].filter(keep));
    const busy = !!pending;
    const job = { id: ++jobId, showings: cands().list, films: S.picked, opts: solverOpts(), swap };
    pending = job;
    S.running = true; S.error = null; S.overlap = undefined; S.alt = null;
    if (!swap) S.note = null;
    render();
    if (busy && worker) { try { worker.terminate(); } catch (_) { /* ignore */ } worker = null; }    // drop a stale solve
    const w = getWorker();
    if (w) { try { w.postMessage(job); return; } catch (_) { worker = false; } }
    solveHere(job);
  }

  function onSolved(msg) {
    if (!msg || msg.id !== jobId) return;
    if (msg.phase === "error") { pending = null; S.running = false; S.error = msg.error; return render(); }
    if (msg.phase === "main") {
      S.result = msg.result;
      S.running = false;
      if (msg.swap) {
        S.excluded = new Set(msg.swap.opts.excluded);
        S.note = msg.swap.adjusted ? "swapAdjusted" : null;
      }
      if (!msg.result.needFallback) { S.overlap = null; pending = null; }
      save();
      return render();
    }
    if (msg.phase === "overlap") { pending = null; S.overlap = msg.result; render(); }
  }

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
  const btn = (label, onclick, cls = "pl-btn", extra = {}) => el("button", Object.assign({ type: "button", class: cls, onclick }, extra), label);
  const chip = (label, on, onclick, extra = {}) =>
    el("button", Object.assign({ type: "button", class: "pl-chip" + (on ? " on" : ""), "aria-pressed": String(on), onclick }, extra), label);

  // ---------- the button that opens the panel ----------
  let openBtn = null;
  /** Main page: beside the view switch. Phone page: first in the row of filter switches above the cards (its
   *  top bar has no room left at 375px — the date would be cut to "1…"); that row is redrawn with the page,
   *  so the button is put back after each redraw. Anything else: a floating button. */
  function inject() {
    const views = document.querySelector("#views");
    const main = document.querySelector(".m-main");
    if (views) {
      openBtn = el("button", { type: "button", class: "pl-open", onclick: () => open() });
      views.after(openBtn);
    } else if (main) {
      openBtn = el("button", { type: "button", class: "m-chip pl-open-chip", onclick: () => open() }, el("span", { class: "pl-ic", "aria-hidden": "true" }), el("span", { class: "pl-lbl" }));
      const place = () => { const row = main.querySelector(".m-chips"); if (row && openBtn.parentNode !== row) row.prepend(openBtn); };
      new MutationObserver(place).observe(main, { childList: true });
      place();
    } else {
      openBtn = el("button", { type: "button", class: "pl-fab", onclick: () => open() });
      document.body.append(openBtn);
    }
    label();
  }
  function label() {
    if (!openBtn) return;
    const target = openBtn.querySelector(".pl-lbl") || openBtn;
    target.textContent = t("plan");
    openBtn.title = t("planT");
    openBtn.setAttribute("aria-label", t("plan"));
    openBtn.setAttribute("aria-haspopup", "dialog");
  }

  // ---------- the panel ----------
  let dlg = null;
  const ui = {};
  function build() {
    ui.title = el("h2", { class: "pl-title", id: "pl-title" });
    ui.steps = el("nav", { class: "pl-steps" });
    ui.close = el("button", { type: "button", class: "pl-x", onclick: () => close() }, "×");
    ui.body = el("div", { class: "pl-body" });
    ui.foot = el("footer", { class: "pl-foot" });
    ui.toast = el("div", { class: "pl-toast", role: "status", "aria-live": "polite" });
    dlg = el("dialog", { class: "planner", "aria-labelledby": "pl-title" },
      el("header", { class: "pl-head" }, ui.title, ui.steps, ui.close), ui.body, ui.foot, ui.toast);
    // keys typed in the panel stay in it (the page underneath uses ← → to change day)
    dlg.addEventListener("keydown", (e) => { if (e.key !== "Escape") e.stopPropagation(); });
    dlg.addEventListener("click", (e) => { if (e.target === dlg) close(); });       // the backdrop
    dlg.addEventListener("cancel", (e) => { e.preventDefault(); close(); });         // Esc
    dlg.addEventListener("close", onClosed);
    document.body.append(dlg);
  }

  let shown = false, pushed = false, ownBack = false;
  function open(step) {
    if (!dlg) build();
    if (dlg.open) return;
    shown = true;
    const resume = step == null && !!S.result && S.picked.length > 0;      // reopened after making plans
    if (step == null) restore();
    S.step = step || (resume ? 3 : 1);
    if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
    document.documentElement.classList.add("pl-open");
    try { history.pushState({ planner: 1 }, "", location.href); pushed = true; } catch (_) { pushed = false; }
    if (S.step === 3) solve(); else render();
    ui.body.scrollTop = 0;
  }
  /** Closing runs the clean-up at once; the dialog's own "close" event (Esc) runs it too, only once. */
  function close() { if (dlg && dlg.open) dlg.close(); onClosed(); }
  function onClosed() {
    if (!shown) return;
    shown = false;
    document.documentElement.classList.remove("pl-open");
    if (pushed && history.state && history.state.planner) { ownBack = true; history.back(); }
    pushed = false;
    if (openBtn) openBtn.focus({ preventScroll: true });
  }
  window.addEventListener("popstate", () => {
    if (ownBack) { ownBack = false; return; }            // the Back that closing the panel made itself
    if (dlg && dlg.open) { pushed = false; close(); }       // the phone's Back button closes the panel
  });

  function go(step) {
    S.step = step;
    if (step === 3) solve();
    else render();
    ui.body.scrollTop = 0;
  }

  function render() {
    if (!dlg) return;
    document.documentElement.classList.toggle("pl-zh", lang() === "zh");
    ui.title.textContent = t("plan");
    ui.close.setAttribute("aria-label", t("close"));
    ui.steps.replaceChildren(...t("steps").map((name, i) => {
      const n = i + 1;
      return el("button", {
        type: "button", class: "pl-step" + (n === S.step ? " on" : ""), "aria-current": n === S.step ? "step" : null,
        disabled: n === 3 && !S.picked.length ? true : null, onclick: () => n !== S.step && go(n),
      }, el("span", { class: "pl-step-n" }, n), el("span", { class: "pl-step-name" }, name));
    }));
    if (S.step === 1) renderRange();
    else if (S.step === 2) renderFilms();
    else renderPlans();
  }

  // ---------- step 1: range ----------
  function renderRange() {
    const today = todayKey();
    const lastDay = dataDays[dataDays.length - 1] || today;
    const count = el("span", { class: "pl-count", "aria-live": "polite" });
    const refreshCount = () => {
      const c = cands();
      count.textContent = t("scopeCount", c.films.length, c.list.length);
      next.disabled = !c.films.length;
    };
    const setPreset = (p) => {
      S.preset = p;
      if (p !== "custom") [S.from, S.to] = presetRange(p, today);
      save(); renderRange();
    };
    const fromIn = el("input", { type: "date", class: "pl-date", value: S.from, min: today, max: lastDay, "aria-label": t("dates"),
      onchange: (e) => { if (!validDay(e.target.value)) return; S.preset = "custom"; S.from = e.target.value < today ? today : e.target.value;
        if (S.to < S.from) S.to = S.from; if (S.to > shiftDay(S.from, 30)) S.to = shiftDay(S.from, 30); save(); renderRange(); } });
    const toIn = el("input", { type: "date", class: "pl-date", value: S.to, min: S.from, max: lastDay, "aria-label": t("to"),
      onchange: (e) => { if (!validDay(e.target.value)) return; S.preset = "custom"; S.to = e.target.value < S.from ? S.from : e.target.value;
        if (S.to > shiftDay(S.from, 30)) S.to = shiftDay(S.from, 30); save(); renderRange(); } });

    const venueBox = el("div", { class: "pl-venues" });
    const fillVenues = () => {
      venueBox.replaceChildren(...REGIONS.map((r) => {
        const list = venues.filter((v) => regionOf(v) === r);
        const allOn = list.every((v) => S.venues.has(v.id));
        return el("div", { class: "pl-region" },
          REGIONS.length > 1 ? chip(r, allOn, () => {
            list.forEach((v) => (allOn ? S.venues.delete(v.id) : S.venues.add(v.id)));
            fillVenues(); refreshCount();
          }, { class: "pl-chip region" + (allOn ? " on" : "") }) : null,
          list.map((v) => chip([el("span", { class: "pl-dot" }), v.short || v.name], S.venues.has(v.id), () => {
            S.venues.has(v.id) ? S.venues.delete(v.id) : S.venues.add(v.id);
            fillVenues(); refreshCount();
          }, { title: v.name, class: "pl-chip venue" + (S.venues.has(v.id) ? " on" : ""), style: `--c:${v.color || "#888"}` })));
      }));
    };
    fillVenues();

    const check = (label, on, onchange) => el("label", { class: "pl-check" },
      el("input", { type: "checkbox", checked: on || null, onchange }), el("span", {}, label));
    const filters = el("div", { class: "pl-row" },
      check(t("onFilm"), S.film, (e) => { S.film = e.target.checked; refreshCount(); }),
      check(t("subs"), S.subs, (e) => { S.subs = e.target.checked; refreshCount(); }),
      check(t("specials"), S.specials, (e) => { S.specials = e.target.checked; refreshCount(); }));

    const time = (value, onchange, aria) => el("input", { type: "time", class: "pl-time-in", value, step: 300, "aria-label": aria, onchange });
    const sel = (opts, value, onchange, aria) => el("select", { class: "pl-select", "aria-label": aria, onchange },
      opts.map(([v, l]) => el("option", { value: String(v), selected: String(v) === String(value) || null }, l)));
    const moreOpen = S.win.on || !!S.maxPerDay || S.forbidTight || S.maxOverlap !== P.DEFAULTS.maxOverlap;
    const more = el("details", { class: "pl-more", open: moreOpen || null },
      el("summary", {}, t("more")),
      el("div", { class: "pl-opt" },
        check(t("window"), S.win.on, (e) => { S.win.on = e.target.checked; save(); refreshCount(); }),
        el("span", { class: "pl-inline" }, el("span", { class: "pl-muted" }, t("earliest")),
          time(S.win.earliest, (e) => { S.win.earliest = e.target.value || "11:00"; S.win.on = true; save(); renderRange(); }, t("earliest")),
          el("span", { class: "pl-muted" }, t("latest")),
          time(S.win.latest, (e) => { S.win.latest = e.target.value || "23:59"; S.win.on = true; save(); renderRange(); }, t("latest")))),
      el("div", { class: "pl-opt" }, el("span", {}, t("perDay")),
        sel([["", t("noLimit")], ...[1, 2, 3, 4, 5, 6].map((n) => [n, t("perDayN", n)])], S.maxPerDay || "",
          (e) => { S.maxPerDay = +e.target.value || null; save(); }, t("perDay"))),
      el("div", { class: "pl-opt" }, check(t("allowTight"), !S.forbidTight, (e) => { S.forbidTight = !e.target.checked; save(); })),
      el("div", { class: "pl-opt" }, el("span", {}, t("miss")),
        sel([[0, t("missOff")], ...[5, 10, 15, 20, 25, 30].map((n) => [n, t("missN", n)])], S.maxOverlap,
          (e) => { S.maxOverlap = +e.target.value || 0; save(); }, t("miss"))));

    ui.body.replaceChildren(el("div", { class: "pl-range" },
      el("section", { class: "pl-sec" }, el("h3", {}, t("dates")),
        el("div", { class: "pl-row" }, PRESETS.map(([p, key]) => chip(t(key), S.preset === p, () => setPreset(p))),
          chip(t("custom"), S.preset === "custom", () => setPreset("custom"))),
        el("div", { class: "pl-row pl-dates" }, fromIn, el("span", { class: "pl-muted" }, t("to")), toIn,
          el("span", { class: "pl-muted pl-span" }, S.from === S.to ? dayLabel(S.from) : `${dayLabel(S.from)} – ${dayLabel(S.to)}`))),
      el("section", { class: "pl-sec" }, el("h3", {}, t("cinemas"),
        el("span", { class: "pl-links" },
          btn(t("selectAll"), () => { S.venues = new Set(venues.map((v) => v.id)); fillVenues(); refreshCount(); }, "pl-link"),
          btn(t("clear"), () => { S.venues = new Set(); fillVenues(); refreshCount(); }, "pl-link"))), venueBox),
      el("section", { class: "pl-sec" }, el("h3", {}, t("filters")), filters),
      more));

    const next = btn(t("toFilms") + " →", () => go(2), "pl-btn primary");
    ui.foot.replaceChildren(count, next);
    refreshCount();
  }

  // ---------- step 2: films ----------
  function renderFilms() {
    const c = cands();
    const inScope = new Set(c.films.map((f) => f.key));
    const top = el("div", { class: "pl-filmbar" });
    const list = el("div", { class: "pl-films", role: "group", "aria-label": t("steps")[1] });
    let timer = null;
    const q = el("input", { type: "search", class: "pl-search", placeholder: t("search"), "aria-label": t("search"), value: S.q,
      autocomplete: "off", spellcheck: "false", enterkeyhint: "search",
      oninput: () => { clearTimeout(timer); timer = setTimeout(() => { S.q = q.value.trim(); fillList(); }, 120); } });
    const sort = el("select", { class: "pl-select", "aria-label": t("sortBy"), onchange: (e) => { S.sort = e.target.value; save(); fillList(); } },
      [["title", t("sortTitle")], ["count", t("sortCount")], ["first", t("sortFirst")]].map(([v, l]) =>
        el("option", { value: v, selected: S.sort === v || null }, l)));

    const picks = el("div", { class: "pl-picks" });
    top.append(el("div", { class: "pl-row pl-tools" }, q, sort), picks);
    const fillTop = () => {
      const k = S.picked.length;
      picks.replaceChildren(...[
        el("div", { class: "pl-pickbar" },
          el("span", { class: "pl-picked" }, t("picked", k)),
          k ? btn(t("clearPicked"), () => { S.picked = []; save(); fillTop(); fillList(); }, "pl-link") : null,
          btn(t("go") + " →", () => go(3), "pl-btn primary", { disabled: !k || null })),
        k > EXACT_FILMS ? el("p", { class: "pl-warn" }, t("approxWarn")) : null,
        k ? el("div", { class: "pl-pickchips" }, S.picked.map((key) => el("button", {
          type: "button", class: "pl-pchip" + (inScope.has(key) ? "" : " out"), title: inScope.has(key) ? null : t("notInScope"),
          onclick: () => toggle(key) }, titleOf(key), el("span", { "aria-hidden": "true" }, " ×")))) : null,
      ].filter(Boolean));
    };
    const toggle = (key) => {
      const i = S.picked.indexOf(key);
      if (i >= 0) S.picked.splice(i, 1);
      else if (S.picked.length >= P.MAX_FILMS) return toast(t("maxPick", P.MAX_FILMS));
      else S.picked.push(key);
      S.result = null;
      save(); fillTop();
      const box = list.querySelector(`[data-key="${CSS.escape(key)}"] input`);
      if (box) box.checked = S.picked.includes(key);
    };
    const where = (f) => f.venues.length <= 2 ? f.venues.map((id) => (venueById[id] || {}).short || id).join(" · ") : t("nVenues", f.venues.length);
    const md = (d) => `${+d.slice(5, 7)}/${+d.slice(8)}`;
    const oneWeek = S.to <= shiftDay(S.from, 6);           // weekday names alone are clear within one week
    const days = (f) => f.days.length > 5 ? `${dayLabel(f.days[0])} – ${dayLabel(f.days[f.days.length - 1])}`
      : f.days.map(oneWeek ? weekday : md).join(" ");
    const fillList = () => {
      const needle = P.fold(S.q);
      let films = c.films;
      if (needle) {
        films = films.filter((f) => P.fold(f.title).includes(needle) || P.fold(f.director).includes(needle) ||
          f.venues.some((id) => P.fold((venueById[id] || {}).name).includes(needle) || P.fold((venueById[id] || {}).short).includes(needle)));
      }
      if (S.sort === "count") films = [...films].sort((a, b) => b.showings.length - a.showings.length);
      if (S.sort === "first") films = [...films].sort((a, b) => a.showings[0].start - b.showings[0].start);
      if (!c.films.length) return list.replaceChildren(el("p", { class: "pl-empty" }, t("noFilms")));
      if (!films.length) return list.replaceChildren(el("p", { class: "pl-empty" }, t("noMatch", S.q)));
      list.replaceChildren(...films.map((f) => {
        const meta = [f.director, f.year, f.runtime_min ? t("minutes", f.runtime_min) : null, f.language, f.formats.join("/")].filter(Boolean).join(" · ");
        return el("label", { class: "pl-film", "data-key": f.key },
          el("input", { type: "checkbox", checked: S.picked.includes(f.key) || null, onchange: (e) => {
            if (e.target.checked !== S.picked.includes(f.key)) toggle(f.key);
            e.target.checked = S.picked.includes(f.key);
          } }),
          el("span", { class: "pl-film-text" },
            el("span", { class: "pl-film-title" }, f.title),
            meta ? el("span", { class: "pl-film-meta" }, meta) : null,
            el("span", { class: "pl-film-where" }, t("filmLine", f.showings.length, where(f)), " · ", days(f))));
      }));
    };
    fillTop(); fillList();
    ui.body.replaceChildren(top, list);
    ui.foot.replaceChildren(btn("← " + t("steps")[0], () => go(1), "pl-btn"), el("span", { class: "pl-count" }, t("scopeCount", c.films.length, c.list.length)));
  }

  // ---------- step 3: plans ----------
  function renderPlans() {
    const r = S.result;
    const out = [];
    if (!S.picked.length) out.push(el("p", { class: "pl-empty" }, t("pickFirst")));
    else if (S.error) out.push(el("p", { class: "pl-note bad" }, t("error"), S.error.split("\n")[0]));
    else if (S.running || !r) out.push(el("p", { class: "pl-busy" }, el("span", { class: "pl-spin", "aria-hidden": "true" }), t("solving")));
    else {
      if (S.shared) out.push(el("p", { class: "pl-note" }, t("sharedNote")));
      if (r.approx) out.push(el("p", { class: "pl-note" }, t("approx")[r.approxReason] || t("approx").size));
      if (S.note === "swapAdjusted") out.push(el("p", { class: "pl-note" }, t("swapAdjusted")));
      if (S.locked.size || S.excluded.size) {
        out.push(el("p", { class: "pl-adj" }, t("adjustments", S.locked.size, S.excluded.size), " ",
          btn(t("resetAdj"), () => { S.locked = new Set(); S.excluded = new Set(); S.shared = false; save(); solve(); }, "pl-link")));
      }
      if (r.lockConflict) {
        out.push(el("p", { class: "pl-note bad" }, t("lockConflict"), " ",
          btn(t("unlockAll"), () => { S.locked = new Set(); S.shared = false; save(); solve(); }, "pl-link")));
      } else if (!r.plans.length || !r.maxFilms) {
        out.push(el("p", { class: "pl-empty" }, t("nothing")));
        if (r.plans[0]) out.push(uncoveredBox(r.plans[0], r, true));
      } else {
        const short = r.maxFilms < r.schedulable;
        r.plans.forEach((p, i) => {
          out.push(card(p, { n: i + 1, r, badge: short ? ["drop", t("badgeDrop", p.stats.of - p.stats.films)] : null, first: i === 0 }));
          if (i === 0 && S.alt != null && r.drop[S.alt]) {
            const d = r.drop[S.alt];
            out.push(card(d, { r, alt: true, badge: ["drop", t("badgeDrop", d.stats.of - d.stats.films)] }));
          }
        });
        if (short && S.overlap === undefined && S.maxOverlap > 0) {
          out.push(el("p", { class: "pl-busy small" }, el("span", { class: "pl-spin", "aria-hidden": "true" }), t("solvingOverlap")));
        }
        if (S.overlap) out.push(card(S.overlap, { n: r.plans.length + 1, r, badge: ["overlap", t("badgeOverlap", S.overlap.stats.overlapMinutes)] }));
      }
    }
    ui.body.replaceChildren(el("div", { class: "pl-plans" }, out));
    ui.foot.replaceChildren(btn("← " + t("steps")[1], () => go(2), "pl-btn"));
    // a day's row that runs past the edge (phones scroll it sideways) fades out until scrolled to its end
    ui.body.querySelectorAll(".pl-chain").forEach((c) => {
      const mark = () => c.classList.toggle("more", c.scrollWidth - c.scrollLeft - c.clientWidth > 2);
      mark();
      c.addEventListener("scroll", mark, { passive: true });
    });
  }

  const venueShort = (id) => (venueById[id] || {}).short || (venueById[id] || {}).name || id;
  const objName = (o) => t("obj")[o] || o;

  function statsLine(p, r) {
    const st = p.stats;
    return [
      t("statFilms", st.films, r.selected),
      t("statDays", st.days),
      st.minGap != null ? t("statMinGap", st.minGap) : null,
      st.tightCount ? t("statTight", st.tightCount) : null,
      st.overlapMinutes ? t("statOverlap", st.overlapMinutes, st.overlapCount) : null,
      (p.objective === "early" || (p.also || []).includes("early")) && st.lastEndMin != null ? t("statLastEnd", clockLabel(st.lastEndMin)) : null,
    ].filter(Boolean).join(" · ");
  }

  function card(p, { n, r, badge, alt, first }) {
    const key = alt ? "alt" : p.objective;          // stays open while the plan under it is recomputed
    const expanded = S.expanded.has(key);
    const head = el("div", { class: "pl-card-head" },
      el("h3", {}, alt ? t("altTitle", p.dropped.map(titleOf).join("、")) : `${t("planN", n)} · ${objName(p.objective)}`,
        !alt && p.also && p.also.length ? el("span", { class: "pl-also" }, t("alsoObj", p.also.map(objName))) : null),
      badge ? el("span", { class: `pl-badge ${badge[0]}` }, badge[1]) : null,
      el("p", { class: "pl-stats", title: alt ? null : t("objT")[p.objective] }, statsLine(p, r)),
      el("div", { class: "pl-actions" },
        CAL ? btn(t("importCal"), (e) => importCal(p, e.currentTarget), "pl-btn small primary") : null,
        btn(expanded ? t("collapse") : t("expand"), () => { expanded ? S.expanded.delete(key) : S.expanded.add(key); render(); }, "pl-btn small",
          { "aria-expanded": String(expanded) }),
        btn(t("share"), () => share(p), "pl-btn small")));
    return el("article", { class: "pl-card" + (badge ? " " + badge[0] : "") + (alt ? " alt" : "") },
      head,
      el("div", { class: "pl-days" }, dayRows(p)),
      uncoveredBox(p, r, first),
      expanded ? legList(p) : null);
  }

  /** One row per day: "周五 10/10  7:00pm Danton · FF → 9:30pm …". */
  function dayRows(p) {
    const byDay = new Map();
    for (const s of p.legs) {
      if (!byDay.has(s.day)) byDay.set(s.day, []);
      byDay.get(s.day).push(s);
    }
    const gapOf = new Map(p.gaps.map((g) => [g.to, g]));
    const titleBy = (s) => s.source.title;
    return [...byDay.entries()].map(([day, legs]) => {
      const chain = [];
      const notes = [];
      legs.forEach((s, i) => {
        if (i) {
          const g = gapOf.get(s.id);
          if (g && g.overlap) {
            chain.push(el("span", { class: "pl-to ov", title: t("overlapT", g.overlap) }, `⇢${g.overlap}′`));
            notes.push(el("div", { class: "pl-miss" }, "⇢ ", t("missLine", titleBy(legs[i - 1]), titleBy(s), g.overlap)));
          } else if (g && g.tight) chain.push(el("span", { class: "pl-to tight", title: t("tightT", g.minutes) }, `⚠${g.minutes}′`));
          else chain.push(el("span", { class: "pl-to", title: g ? t("gapT", g.minutes) : null }, "→"));
        }
        const unknown = !s.endKnown;
        chain.push(el("span", { class: "pl-leg" + (S.locked.has(s.id) ? " locked" : "") },
          el("span", { class: "pl-tm", title: unknown ? t("unknownRt") : null }, timeLabel(s.start, s.tz), unknown ? "?" : ""), " ",
          el("span", { class: "pl-ti" }, titleBy(s)), el("span", { class: "pl-vn" }, " · ", venueShort(s.venue_id)),
          S.locked.has(s.id) ? el("span", { class: "pl-lock", title: t("lockedTag"), "aria-label": t("lockedTag") }, " 🔒") : null));
      });
      return el("div", { class: "pl-day" },
        el("span", { class: "pl-dl" }, dayLabel(day)),
        el("div", { class: "pl-chain" }, chain),
        notes.length ? el("div", { class: "pl-notes" }, notes) : null);
    });
  }

  function whyText(u, r) {
    const W = t("why");
    if (u.reason === "none") return W.none;
    if (u.reason === "excluded") return W.excluded;
    if (u.reason === "limit") return W.limit;
    const w = (u.with || []).map(titleOf).join(lang() === "zh" ? "、" : ", ");
    if (u.only) {
      const s = cands().list.find((x) => x.id === u.only);
      if (s) return W.only(`${dayLabel(s.day)} ${timeLabel(s.start, s.tz)}`, w);
    }
    return W.many(u.count, w);
  }

  function uncoveredBox(p, r, first) {
    if (!p.uncovered.length) return null;
    const sep = lang() === "zh" ? "；" : "; ";
    const items = p.uncovered.map((u) => `${titleOf(u.filmKey)}${lang() === "zh" ? "（" : " ("}${whyText(u, r)}${lang() === "zh" ? "）" : ")"}`);
    const alts = first && p.objective !== "drop" && r.drop.length ? el("div", { class: "pl-alts" }, t("orDrop"),
      r.drop.map((d, i) => {
        const desc = d.stats.tightCount ? t("altTight", d.stats.tightCount) : t("altEasy");
        const many = p.uncovered.filter((u) => u.reason !== "none" && u.reason !== "excluded").length > 1;
        const lbl = d.dropped.map(titleOf).join("、") + (many ? " " + t("altGain", d.gained.map(titleOf).join("、")) : "") +
          (lang() === "zh" ? `（${desc}）` : ` (${desc})`);
        return chip(lbl, S.alt === i, () => { S.alt = S.alt === i ? null : i; render(); }, { class: "pl-chip alt" + (S.alt === i ? " on" : "") });
      })) : null;
    return el("div", { class: "pl-uncovered" }, el("span", { class: "pl-label" }, t("uncovered")), items.join(sep), alts);
  }

  /** The expanded plan: a row per screening with its links and lock / exclude / another showing. */
  function legList(p) {
    const lg = lang();
    return el("ol", { class: "pl-legs" }, p.legs.map((s) => {
      const v = venueById[s.venue_id] || {};
      const src = s.source;
      const locked = S.locked.has(s.id);
      const meta = [src.director, src.year, src.runtime_min ? t("minutes", src.runtime_min) : null, src.format, src.language].filter(Boolean).join(" · ");
      const ev = CAL ? CAL.eventFor(src, v, lg) : null;
      return el("li", { class: "pl-legrow" + (locked ? " locked" : "") },
        el("div", { class: "pl-when" }, `${dayLabel(s.day)} · ${timeLabel(s.start, s.tz)} – ${timeLabel(s.end, s.tz)}${s.endKnown ? "" : "?"}`,
          locked ? el("span", { class: "pl-tag" }, t("lockedTag")) : null),
        el("div", { class: "pl-what" }, el("strong", {}, src.title)),
        el("div", { class: "pl-where" }, el("span", { class: "pl-dot", style: `--c:${v.color || "#888"}` }),
          [v.name, s.screen && s.screen !== v.name ? s.screen : null].filter(Boolean).join(" · ")),
        meta ? el("div", { class: "pl-meta" }, meta) : null,
        !s.endKnown ? el("div", { class: "pl-meta" }, t("unknownRt")) : null,
        src.series || src.note ? el("div", { class: "pl-meta" }, [src.series, src.note].filter(Boolean).join(" · ")) : null,
        el("div", { class: "pl-legacts" },
          s.ticket_url ? el("a", { class: "pl-btn small", href: s.ticket_url, target: "_blank", rel: "noopener" }, t("tickets")) : null,
          s.detail_url && s.detail_url !== s.ticket_url ? el("a", { class: "pl-btn small", href: s.detail_url, target: "_blank", rel: "noopener" }, t("details")) : null,
          ev ? el("a", { class: "pl-btn small", href: CAL.googleUrl(ev, CAL.isMobile()), target: "_blank", rel: "noopener" }, t("google")) : null,
          el("span", { class: "pl-sep" }),
          btn(locked ? t("unlock") : t("lock"), () => { locked ? S.locked.delete(s.id) : S.locked.add(s.id); S.shared = S.shared && S.locked.size > 0; save(); solve(); }, "pl-btn small"),
          btn(t("exclude"), () => { S.excluded.add(s.id); S.locked.delete(s.id); save(); solve(); }, "pl-btn small"),
          btn(t("swap"), () => swapLeg(p, s), "pl-btn small")));
    }));
  }

  function swapLeg(p, s) {
    const others = cands().list.filter((x) => x.filmKey === s.filmKey && x.id !== s.id && !S.excluded.has(x.id));
    if (!others.length) return toast(t("swapNone", s.source.title));
    S.locked.delete(s.id);
    // the plan's other screenings stay (unless that leaves the film out — plan.js then lets them move)
    solve({ legs: p.legs.map((x) => x.id), leg: s.id });
  }

  // ---------- calendar, share ----------
  function importCal(p, button) {
    if (CAL.iosNeedsSafari()) return toast(t("calSafari"), 6000);
    const events = p.legs.map((s) => CAL.eventFor(s.source, venueById[s.venue_id], lang()));
    CAL.download(CAL.toICS(events), `showtimes-plan-${S.from}.ics`);
    if (!CAL.isIOS()) toast(t("calSaved"));
    if (button) button.blur();
  }

  function shareUrl(p) {
    // the plan's screenings travel locked, so the link opens on this very plan (an overlap plan can't be
    // locked — two of its screenings overlap — so it travels as its films and options)
    const locked = p && p.objective !== "overlap" ? [...new Set([...S.locked, ...p.legs.map((s) => s.id)])] : [...S.locked];
    const all = venues.every((v) => S.venues.has(v.id));
    const payload = P.toShare({
      from: S.from, to: S.to, venues: all ? null : [...S.venues], film: S.film, subs: S.subs, specials: S.specials,
      dayWindow: S.win.on ? { earliest: S.win.earliest, latest: S.win.latest } : null, maxPerDay: S.maxPerDay,
      forbidTight: S.forbidTight, maxOverlap: S.maxOverlap, films: S.picked, locked, excluded: [...S.excluded],
    });
    const phone = !document.querySelector("#views") && /\/m\/[^/]+\/(index\.html)?$/.test(location.pathname);
    const u = new URL(phone ? "../../index.html" : location.href, location.href);
    u.search = "?plan=" + P.encode(payload);
    u.hash = "#/" + (S.from > todayKey() ? S.from : "");
    return u.href;
  }

  async function share(p) {
    const url = shareUrl(p);
    if (navigator.share && CAL && CAL.isMobile()) {
      try { await navigator.share({ title: `${t("plan")} · Corridor Showtimes`, url }); return; }
      catch (e) { if (e && e.name === "AbortError") return; }
    }
    try { await navigator.clipboard.writeText(url); toast(t("linkCopied")); }
    catch (_) { window.prompt(t("copyThis"), url); }
  }

  let toastTimer = null;
  function toast(msg, ms = 3500) {
    clearTimeout(toastTimer);
    ui.toast.textContent = msg;
    ui.toast.classList.add("show");
    toastTimer = setTimeout(() => ui.toast.classList.remove("show"), ms);
  }

  // ---------- start ----------
  function start() {
    if (history.state && history.state.planner) history.replaceState(null, "", location.href);   // reloaded with the panel open
    inject();
    let shownLang = lang();
    new MutationObserver(() => {
      if (lang() === shownLang) return;          // both pages set the attribute on every render
      shownLang = lang();
      label();
      if (dlg && dlg.open) render();
    }).observe(document.documentElement, { attributes: true, attributeFilter: ["lang"] });
    if (/[?&]plan=/.test(location.search)) {
      restore();
      if (fromLink()) open(3);
    }
  }
  if (document.querySelector("#views, .m-main")) start();
  else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
