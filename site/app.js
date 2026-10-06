/* Corridor Showtimes — plain JS, no build step.
 * All DOM is derived from window.CINEMA_DATA + `state` by the render* functions.
 * State lives in the URL hash, e.g.
 *   #/2026-09-24?view=list&v=bam,filmlinc&r=NYC&film=1&up=1&q=wong&ws=today&hl=Happy%20Together
 * Times are shown in each cinema's own time zone (venues[].timezone); "today" is the viewer's date.
 */
(function () {
  "use strict";

  const DEFAULT_TZ = "America/New_York";
  const DATA = window.CINEMA_DATA || { venues: [], screenings: [], days: {}, generated_at: null };
  const LS_VENUES = "cinema.venues";
  const LS_REGIONS = "cinema.regions";
  const REPO = "https://github.com/Marc506/corridor-showtimes";
  const FILM_FORMATS = new Set(["16mm", "35mm", "70mm", "Film"]);   // "Film" = on film, gauge unknown (screenslate)
  const DEFAULT_RUNTIME = 100;           // minutes, for blocks without a runtime (dashed border)
  const NARROW = window.matchMedia("(max-width: 640px)");
  const LS_LANG = "cinema.lang";

  // ---------- i18n ----------
  const I18N = {
    zh: {
      never: "从未", justNow: "刚刚", minAgo: (n) => `${n} 分钟前`, hrAgo: (n) => `${n} 小时前`, dayAgo: (n) => `${n} 天前`,
      updated: (r) => `更新于 ${r}`, noDataYet: "还没有数据 — 先运行 python -m scraper.run",
      staleHint: " · 自动更新可能没开", staleHintT: "在项目文件夹里对 AI 助手说「开启每天自动更新」，或运行 python -m scraper.schedule on（查看状态：python -m scraper.schedule status）",
      viaTitle: (src) => `主源不可用，今天的数据来自兜底源 ${src}（可能不全）`, viaTag: (src) => `主源抓取失败，数据来自 ${src}`,
      dataFrom: (a) => `数据来自影院的 ${a} 系统`,
      customize: "＋ 自定义影院",
      guideTitle: "添加你自己的影院",
      guideIntro: "这个网站只收录作者关注的影院。想看别的影院？可以在你自己的电脑上，让 AI 编程助手帮你加进去：免费，不用写代码，大约 10–20 分钟。",
      guideSteps: [
        ["准备一个能在电脑上运行程序的 AI 助手：", "Claude Code、Cursor 或 Codex 都可以。ChatGPT 网页版这类只能聊天的不行。"],
        ["下载本项目：", "打开 GitHub 页面，点绿色的「Code」按钮 →「Download ZIP」，下载后双击解压。"],
        ["在 AI 助手里打开解压出来的文件夹，发送这句话：", null],
        ["按它的提示回答：", "它会问你影院名和排片页的网址；要安装软件或运行命令时，点「允许」。"],
        ["完成后，它会告诉你打开哪个文件查看，并问要不要每天自动更新：回答「好」。", "之后电脑开着时，每天 1:00 和 13:00 自动更新。注意：你加的影院只在你自己的电脑上，不会出现在这个网站里。"],
      ],
      guidePrompt: "请阅读这个文件夹里的 AGENTS.md，帮我添加一家影院。",
      copy: "复制", copied: "已复制",
      guideGithub: "打开 GitHub 页面", guideFull: "完整图文教程（含常见问题）",
      guideHelp: "实在解决不了？在 GitHub 上提一个 Issue，附上影院名、网址和 AI 助手最后说的话。", guideHelpLink: "提 Issue", website: "影院官网", regions: "区域", allRegions: "全部区域",
      stale: (r) => `旧数据 · ${r}`, failed: "抓取失败",
      prevWeek: "← 上周", nextWeek: "下周 →", thisWeek: "本周", prevWeekT: "上周 (←)", nextWeekT: "下周 (→)",
      today: "今天", todaySuffix: " · 今天", prevDayT: "前一天 (←)", nextDayT: "后一天 (→)",
      hiddenUnknown: (n) => ` · ${n} 场语言未知已隐藏`, hiddenUnknownT: "这些场次的影院网站和 TMDB 都没有语言信息",
      chipStatus: "状态", chipLastOk: "最后成功", chipNever: "从未成功抓取", chipUntil: "数据到", chipError: "错误",
      only: "只看", onlyT: "只看这家", filmsShows: (f, n) => `${f} 部 · ${n} 场`,
      weekEmpty: "这一周所选影院没有符合条件的放映。", openDayT: "打开这一天的时间轴",
      weekFilmT: (t, n) => `${t} — ${n} 场，点击看这天的时间轴`, notAnnounced: "未公布",
      minutes: (n) => `${n} 分钟`, close: "关闭", runtimeUnknown: "（时长未知）", tickets: "购票", details: "详情",
      showingN: (n) => `第 ${n} 场`,
      addCal: "加入日历", appleCal: "Apple 日历", googleCal: "Google 日历",
      addCalT: "加入 Apple 日历等日历应用（.ics 文件，含时间、片名和影院地址）",
      googleCalT: "在 Google 日历里新建这场（会打开 Google 日历网页，确认后点保存）",
      calSaved: "已下载日历文件，打开它即可加入日历。", calSafari: "加入 Apple 日历要在 Safari 里打开本页再点；Google 日历在这里也能用。",
      noData: ["还没有数据。在项目目录运行 ", " 然后刷新本页。"], noVenues: "没有选中任何影院。", selectAll: "全选",
      dayEmpty: "这一天所选影院没有符合条件的放映。", clearFilters: "清除筛选",
      searchSummary: (q, n, f) => `搜索「${q}」：${f} 部 · ${n} 场`, clearSearch: "清除搜索",
      searchNone: (q) => `从今天起，所选影院没有和「${q}」匹配的场次（按片名、导演和系列搜索）。`,
      tomorrowSuffix: " · 明天",
      range: (a, b) => `数据范围 ${a} – ${b}`, total: (n) => `${n} 场放映`, disabled: (l) => `未启用: ${l.join("、")}`,
      dashedNote: "时间轴里虚线框 = 时长未知（按 100 分钟画）",
      credits: ["排片版权归各影院所有，购票请点击链接前往影院官网。语言和导演数据来自 ", "（This product uses the TMDB API but is not endorsed or certified by TMDB）· "],
      source: "源代码", switchTo: "EN", switchToT: "Switch to English",
      // static page text (index.html data-i18n keys)
      views: "视图", timeline: "时间轴", list: "列表", week: "周", dateNav: "日期", pickDate: "选择日期", venues: "影院",
      onFilm: "只看胶片", subs: "有字幕", subsT: "只显示有字幕可看的场次：非英语片（英文字幕）、开放字幕场次（Open captions）和默片",
      upcoming: "隐藏已开场", specials: "影展",
      fromToday: "从今天起", search: "搜索片名 / 导演",
    },
    en: {
      never: "never", justNow: "just now", minAgo: (n) => `${n} min ago`, hrAgo: (n) => `${n} h ago`, dayAgo: (n) => `${n} days ago`,
      updated: (r) => `Updated ${r}`, noDataYet: "No data yet — run python -m scraper.run",
      staleHint: " · automatic updates may be off", staleHintT: "Ask your AI assistant in the project folder to \"turn on daily updates\", or run python -m scraper.schedule on (check: python -m scraper.schedule status)",
      viaTitle: (src) => `Primary source unavailable; today's data comes from the fallback, ${src} (may be incomplete)`,
      viaTag: (src) => `Primary source failed; data from ${src}`,
      dataFrom: (a) => `Data from the cinema's ${a} system`,
      customize: "+ Add your cinemas",
      guideTitle: "Add your own cinemas",
      guideIntro: "This site only follows the cinemas its author goes to. Want others? An AI coding assistant can add them on your own computer — free, no coding, about 10–20 minutes.",
      guideSteps: [
        ["Get an AI assistant that can run programs on your computer:", "Claude Code, Cursor or Codex. Chat-only assistants such as the ChatGPT website can't do this."],
        ["Download this project:", "open the GitHub page, click the green “Code” button → “Download ZIP”, then double-click the file to unzip it."],
        ["Open the unzipped folder in your AI assistant and send:", null],
        ["Answer its questions:", "it asks for the cinema's name and the web page that lists showtimes; when it asks to install something or run a command, allow it."],
        ["When it's done it tells you which file to open, and asks whether to update every day: say yes.", "From then on it refreshes at 01:00 and 13:00 whenever your computer is on. Note: the cinemas you add live on your computer only — they don't appear on this website."],
      ],
      guidePrompt: "Please read AGENTS.md in this folder and help me add a cinema.",
      copy: "Copy", copied: "Copied",
      guideGithub: "Open the GitHub page", guideFull: "Full step-by-step guide (with FAQ)",
      guideHelp: "Stuck? Open an issue on GitHub with the cinema's name, its URL and the assistant's last message.", guideHelpLink: "Open an issue", website: "Cinema website", regions: "Regions", allRegions: "All regions",
      stale: (r) => `Stale · ${r}`, failed: "Fetch failed",
      prevWeek: "← Prev week", nextWeek: "Next week →", thisWeek: "This week", prevWeekT: "Previous week (←)", nextWeekT: "Next week (→)",
      today: "Today", todaySuffix: " · Today", prevDayT: "Previous day (←)", nextDayT: "Next day (→)",
      hiddenUnknown: (n) => ` · ${n} with unknown language hidden`, hiddenUnknownT: "Neither the cinema's site nor TMDB lists a language for these",
      chipStatus: "Status", chipLastOk: "Last success", chipNever: "Never fetched successfully", chipUntil: "Data through", chipError: "Error",
      only: "only", onlyT: "Show only this cinema",
      filmsShows: (f, n) => `${f} film${f === 1 ? "" : "s"} · ${n} show${n === 1 ? "" : "s"}`,
      weekEmpty: "No matching screenings at the selected cinemas this week.", openDayT: "Open this day's timeline",
      weekFilmT: (t, n) => `${t} — ${n} show${n === 1 ? "" : "s"}; click for that day's timeline`, notAnnounced: "not yet listed",
      minutes: (n) => `${n} min`, close: "Close", runtimeUnknown: " (runtime unknown)", tickets: "Tickets", details: "Details",
      showingN: (n) => `Showing ${n}`,
      addCal: "Add to calendar", appleCal: "Apple Calendar", googleCal: "Google Calendar", addCalT: "Add to Apple Calendar or any calendar app (.ics file with the time, title and the cinema's address)",
      googleCalT: "Create this screening in Google Calendar (opens Google Calendar; check it and press Save)",
      calSaved: "Calendar file downloaded — open it to add the event.", calSafari: "For Apple Calendar, open this page in Safari and add it there; Google Calendar works here too.",
      noData: ["No data yet. Run ", " in the project folder, then reload."], noVenues: "No cinemas selected.", selectAll: "All",
      dayEmpty: "No matching screenings at the selected cinemas on this day.", clearFilters: "Clear filters",
      searchSummary: (q, n, f) => `“${q}”: ${f} film${f === 1 ? "" : "s"} · ${n} show${n === 1 ? "" : "s"}`, clearSearch: "Clear search",
      searchNone: (q) => `No screenings matching “${q}” from today on at the selected cinemas (title, director and series are searched).`,
      tomorrowSuffix: " · Tomorrow",
      range: (a, b) => `Data ${a} – ${b}`, total: (n) => `${n} screenings`, disabled: (l) => `Disabled: ${l.join(", ")}`,
      dashedNote: "Dashed blocks = runtime unknown (drawn as 100 min)",
      credits: ["Showtimes belong to the cinemas — use the links to buy tickets from them. Language and director data from ", " (this product uses the TMDB API but is not endorsed or certified by TMDB) · "],
      source: "Source code", switchTo: "中文", switchToT: "切换到中文",
      views: "Views", timeline: "Timeline", list: "List", week: "Week", dateNav: "Date", pickDate: "Pick a date", venues: "Cinemas",
      onFilm: "On film", subs: "Subtitled / captioned", subsT: "Only screenings you can follow by reading: non-English films (English subtitles), open-caption screenings and silent films",
      upcoming: "Hide started", specials: "Festivals",
      fromToday: "Start today", search: "Search title / director",
    },
  };

  function initialLang() {
    const fromUrl = (location.hash.match(/[?&]lang=(zh|en)\b/) || [])[1];
    if (fromUrl) {
      try { localStorage.setItem(LS_LANG, fromUrl); } catch (_) { /* ignore */ }   // the hash is rewritten on load
      return fromUrl;
    }
    try { const saved = localStorage.getItem(LS_LANG); if (saved === "zh" || saved === "en") return saved; } catch (_) { /* ignore */ }
    return /^zh\b/i.test(navigator.language || "") ? "zh" : "en";
  }
  let LANG = initialLang();
  const t = (key, ...args) => { const v = I18N[LANG][key]; return typeof v === "function" ? v(...args) : v; };

  // ---------- time helpers (Intl only; one set of formatters per cinema time zone) ----------
  const fmtCache = new Map();
  function fmts(tz) {
    if (!fmtCache.has(tz)) {
      fmtCache.set(tz, {
        dayKey: new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }),
        time: new Intl.DateTimeFormat("en-US", { timeZone: tz, hour: "numeric", minute: "2-digit" }),
        hm: new Intl.DateTimeFormat("en-US", { timeZone: tz, hour: "numeric", minute: "numeric", hourCycle: "h23" }),
        zone: new Intl.DateTimeFormat("en-US", { timeZone: tz, timeZoneName: "short" }),
      });
    }
    return fmtCache.get(tz);
  }
  const fmtLocalDayKey = new Intl.DateTimeFormat("en-CA", { year: "numeric", month: "2-digit", day: "2-digit" });
  const VIEWER_TZ = (() => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone; } catch (_) { return DEFAULT_TZ; } })();
  const fmtDayTitle = new Intl.DateTimeFormat("zh-CN", { timeZone: "UTC", month: "long", day: "numeric", weekday: "short" });
  const fmtDayTitleEn = new Intl.DateTimeFormat("en-US", { timeZone: "UTC", weekday: "long", month: "short", day: "numeric" });
  const fmtWeekHeadZh = new Intl.DateTimeFormat("zh-CN", { timeZone: "UTC", month: "numeric", day: "numeric", weekday: "short" });
  const fmtWeekHeadEn = new Intl.DateTimeFormat("en-US", { timeZone: "UTC", weekday: "short", month: "numeric", day: "numeric" });
  const fmtWeekHead = { format: (d) => (LANG === "zh" ? fmtWeekHeadZh : fmtWeekHeadEn).format(d) };

  const todayKey = () => fmtLocalDayKey.format(new Date());                                  // the viewer's date
  /** "7:00pm" in the cinema's time zone. */
  const timeLabel = (iso, tz = DEFAULT_TZ) => fmts(tz).time.format(new Date(iso)).replace(" ", "").toLowerCase();
  const zoneLabel = (iso, tz) => (fmts(tz).zone.formatToParts(new Date(iso)).find((p) => p.type === "timeZoneName") || {}).value || "";
  const dayDate = (key) => new Date(key + "T12:00:00Z");                                      // noon UTC: safe for date math
  const shiftDay = (key, n) => { const d = dayDate(key); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
  const validDay = (s) => /^\d{4}-\d{2}-\d{2}$/.test(s || "") && !isNaN(dayDate(s));

  /** Minutes since midnight of `day` in time zone `tz` (can exceed 1440 for after-midnight shows). */
  function minutesInDay(iso, day, tz = DEFAULT_TZ) {
    const f = fmts(tz);
    const [h, m] = f.hm.format(new Date(iso)).split(":").map(Number);
    const d = f.dayKey.format(new Date(iso));
    return h * 60 + m + (d > day ? 1440 : d < day ? -1440 : 0);
  }

  function relTime(iso) {
    if (!iso) return t("never");
    const mins = Math.round((Date.now() - new Date(iso)) / 60000);
    if (mins < 1) return t("justNow");
    if (mins < 60) return t("minAgo", mins);
    const h = Math.round(mins / 60);
    if (h < 48) return t("hrAgo", h);
    return t("dayAgo", Math.round(h / 24));
  }

  const fold = (s) => (s || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();

  // ---------- indexes ----------
  const venueById = Object.fromEntries(DATA.venues.map((v) => [v.id, v]));
  const screeningById = Object.fromEntries(DATA.screenings.map((s) => [s.id, s]));
  const activeVenues = DATA.venues.filter((v) => v.status !== "disabled");
  const dataDays = Object.keys(DATA.days).sort();
  const regionOf = (v) => v.region || v.city || "";
  const REGIONS = [...new Set(activeVenues.map(regionOf))];
  const tzOf = (s) => (venueById[s.venue_id] || {}).timezone || DEFAULT_TZ;
  const isFallback = (src) => !!src && src !== "primary";
  /** A film starting at the same time on two screens (or in two buildings) of one cinema: "twins". */
  const twinKey = (s) => `${s.venue_id}|${s.start}|${fold(s.title)}`;
  const twinCount = new Map();
  for (const s of DATA.screenings) twinCount.set(twinKey(s), (twinCount.get(twinKey(s)) || 0) + 1);
  const hasTwin = (s) => twinCount.get(twinKey(s)) > 1;

  // ---------- state <-> URL hash ----------
  const VIEWS = ["timeline", "list", "week"];
  const state = {
    day: todayKey(), view: "timeline", venues: new Set(activeVenues.map((v) => v.id)), regions: new Set(REGIONS),
    film: false, subs: false, upcoming: false, specials: false, q: "", weekFromToday: false, hl: "",
  };

  /** Stored as {on: [...], known: [...]} — venues added to the site later start selected. */
  function loadStoredVenues() {
    try {
      const raw = JSON.parse(localStorage.getItem(LS_VENUES) || "null");
      if (raw) {
        const on = Array.isArray(raw) ? raw : raw.on || [];
        const known = new Set(Array.isArray(raw) ? [] : raw.known || []);
        const ids = activeVenues.map((v) => v.id).filter((id) => on.includes(id) || !known.has(id));
        if (ids.length) return new Set(ids);
      }
    } catch (_) { /* storage unavailable or corrupt */ }
    return null;
  }

  function storeVenues() {
    try {
      localStorage.setItem(LS_VENUES, JSON.stringify({ on: [...state.venues], known: activeVenues.map((v) => v.id) }));
    } catch (_) { /* ignore */ }
  }

  function loadStoredRegions() {
    try {
      const raw = JSON.parse(localStorage.getItem(LS_REGIONS) || "null");
      if (Array.isArray(raw)) {
        const on = REGIONS.filter((r) => raw.includes(r));
        if (on.length || !raw.length) return new Set(on);     // [] = every region switched off on purpose
      }
    } catch (_) { /* storage unavailable or corrupt */ }
    return null;
  }

  function storeRegions() {
    try { localStorage.setItem(LS_REGIONS, JSON.stringify([...state.regions])); } catch (_) { /* ignore */ }
  }

  /** A cinema is shown when it is selected and its region is selected. */
  const shown = (vid) => state.venues.has(vid) && state.regions.has(regionOf(venueById[vid] || {}));
  const venuesInRegions = () => activeVenues.filter((v) => state.regions.has(regionOf(v)));

  /** A date in the URL is kept only if it isn't in the past: reopened tabs, bookmarks and home-screen
   *  launches come back with yesterday's hash, and those should land on today. (Going back to an
   *  earlier day with ← still works; it just isn't what a fresh visit starts on.) */
  function readHash() {
    const m = location.hash.match(/^#\/([^?]*)(?:\?(.*))?$/);
    const p = new URLSearchParams(m ? m[2] || "" : "");
    const today = todayKey();
    state.day = m && validDay(m[1]) && m[1] >= today ? m[1] : today;
    state.view = VIEWS.includes(p.get("view")) ? p.get("view") : "timeline";
    if (p.has("v")) {
      const ids = p.get("v").split(",").filter((id) => venueById[id]);
      state.venues = new Set(ids.length ? ids : activeVenues.map((v) => v.id));
    } else {
      state.venues = loadStoredVenues() || new Set(activeVenues.map((v) => v.id));
    }
    if (p.has("r")) {
      const raw = p.get("r");
      const rs = raw.split(",").filter((r) => REGIONS.includes(r));
      state.regions = new Set(rs.length || !raw ? rs : REGIONS);           // "r=" = none on; unknown names = all
    } else {
      state.regions = loadStoredRegions() || new Set(REGIONS);
    }
    state.film = p.get("film") === "1";
    state.subs = p.get("sub") === "1";
    state.upcoming = p.get("up") === "1";
    state.specials = p.get("sp") === "1";
    state.q = p.get("q") || "";
    state.weekFromToday = p.get("ws") === "today";
    state.hl = p.get("hl") || "";
  }

  function writeHash() {
    const p = new URLSearchParams();
    if (state.view !== "timeline") p.set("view", state.view);
    const all = state.venues.size === activeVenues.length && activeVenues.every((v) => state.venues.has(v.id));
    if (!all) p.set("v", [...state.venues].join(","));
    if (state.regions.size < REGIONS.length) p.set("r", [...state.regions].join(","));
    if (state.film) p.set("film", "1");
    if (state.subs) p.set("sub", "1");
    if (state.upcoming) p.set("up", "1");
    if (state.specials) p.set("sp", "1");
    if (state.q) p.set("q", state.q);
    if (state.weekFromToday) p.set("ws", "today");
    if (state.hl) p.set("hl", state.hl);
    const q = p.toString().replace(/%2C/g, ",");
    const dayPart = state.day === todayKey() ? "" : state.day;     // "today" stays date-less in the URL
    const hash = `#/${dayPart}${q ? "?" + q : ""}`;
    if (location.hash !== hash) history.replaceState(null, "", hash);
  }

  function update(patch) {
    Object.assign(state, patch);
    if (patch.venues) storeVenues();
    if (patch.regions) storeRegions();
    writeHash();
    render();
  }

  // ---------- data selection ----------
  function screeningsForDay(day) {
    return (DATA.days[day] || []).map((id) => screeningById[id]).filter(Boolean);
  }

  /** Global filters shared by every view (venue chips excluded — callers decide). */
  /** true = subtitled / silent (safe without English listening), false = English, null = unknown. */
  function needsNoEnglish(s) {
    if (/open caption|\bsubtitled\b/i.test(s.note || "")) return true;   // captioned / subtitled screening, any language
    if (!s.language) return null;
    return s.language.split(",")[0].trim().toLowerCase() !== "english";
  }

  function passesFilters(s, now = new Date(), ignoreSubs = false) {
    if (state.film && !FILM_FORMATS.has(s.format)) return false;
    if (state.subs && !ignoreSubs && needsNoEnglish(s) !== true) return false;
    if (state.upcoming && s.day === todayKey() && new Date(s.start) < now) return false;
    if (state.specials && s.run) return false;        // "Festivals": hides new films in their regular run (scraper/export.py)
    if (state.q) {
      const q = fold(state.q);
      if (!fold(s.title).includes(q) && !fold(s.director).includes(q) && !fold(s.series).includes(q)) return false;
    }
    return true;
  }

  function visibleForDay(day) {
    const now = new Date();
    return screeningsForDay(day).filter((s) => shown(s.venue_id) && passesFilters(s, now));
  }

  /** Collapse screenings of the same programme at the same venue into one row (whatever the screen or
   *  building: those only matter once someone adds a screening to a calendar). */
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

  function groupByVenue(list) {
    const byVenue = new Map();
    for (const s of list) {
      if (!byVenue.has(s.venue_id)) byVenue.set(s.venue_id, []);
      byVenue.get(s.venue_id).push(s);
    }
    const earliest = (l) => l.reduce((m, s) => Math.min(m, Date.parse(s.start)), Infinity);
    // venues ordered by their earliest screening of the day (compared as instants)
    return [...byVenue.entries()].sort((a, b) => earliest(a[1]) - earliest(b[1]));
  }

  // ---------- DOM helpers ----------
  const $ = (sel) => document.querySelector(sel);

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "style") node.style.cssText = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v);
    }
    for (const c of children.flat()) {
      if (c == null || c === false) continue;
      node.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return node;
  }

  const link = (href, cls, text) => href
    ? el("a", { class: cls, href, target: "_blank", rel: "noopener" }, text)
    : el("span", { class: cls }, text);

  function filmMeta(s) {
    const parts = [s.director, s.year, s.runtime_min ? `${s.runtime_min}m` : null, s.format, s.language].filter(Boolean);
    return parts.length ? ` (${parts.join(", ")})` : "";
  }

  function statusBadge(v) {
    if (v.status === "ok" && isFallback(v.source)) {
      return el("span", { class: "badge ss", title: `${t("viaTitle", v.source)}\n${v.error || ""}` }, `via ${v.source}`);
    }
    if (v.status === "stale") return el("span", { class: "badge", title: v.error || "" }, t("stale", relTime(v.fetched_at)));
    if (v.status === "failed") return el("span", { class: "badge failed", title: v.error || "" }, t("failed"));
    return null;
  }

  const viaBadge = (s) => isFallback(s.source)
    ? el("span", { class: "tag via", title: t("viaTag", s.source) }, `via ${s.source}`) : null;

  // ---------- render ----------
  /** Static text in index.html carries data-i18n / -title / -placeholder / -aria keys. */
  function applyStaticText() {
    document.documentElement.lang = LANG === "zh" ? "zh-CN" : "en";
    document.querySelectorAll("[data-i18n]").forEach((n) => { n.textContent = t(n.dataset.i18n); });
    document.querySelectorAll("[data-i18n-title]").forEach((n) => { n.title = t(n.dataset.i18nTitle); });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((n) => { n.placeholder = t(n.dataset.i18nPlaceholder); });
    document.querySelectorAll("[data-i18n-aria]").forEach((n) => n.setAttribute("aria-label", t(n.dataset.i18nAria)));
    const btn = $("#lang-toggle");
    btn.textContent = t("switchTo");
    btn.title = t("switchToT");
  }

  function setLang(lang) {
    LANG = lang;
    try { localStorage.setItem(LS_LANG, lang); } catch (_) { /* ignore */ }
    render();
  }

  function render() {
    hidePopover();
    applyStaticText();
    document.body.dataset.view = state.view;
    document.body.classList.toggle("searching", !!state.q);
    renderHeader();
    renderRegions();
    renderChips();
    if (state.q) renderSearch();
    else if (state.view === "week") renderWeek();
    else if (state.view === "list") renderList();
    else renderTimeline();
    renderFooter();
  }

  function weekStart() {
    if (state.weekFromToday) return state.day;
    const dow = dayDate(state.day).getUTCDay();          // 0 = Sunday … 4 = Thursday
    return shiftDay(state.day, -((dow - 4 + 7) % 7));    // back to Thursday (NYC programme change day)
  }

  function renderHeader() {
    const gen = DATA.generated_at;
    const fresh = $("#freshness");
    const stale = !gen || Date.now() - new Date(gen) > 36 * 3600e3;
    const local = location.protocol === "file:";          // someone's own copy, not the public site
    fresh.textContent = gen ? t("updated", relTime(gen)) + (stale && local ? t("staleHint") : "") : t("noDataYet");
    fresh.title = gen ? new Date(gen).toLocaleString() + (stale && local ? "\n" + t("staleHintT") : "") : "";
    fresh.classList.toggle("old", stale);

    document.querySelectorAll("#views button").forEach((b) =>
      b.setAttribute("aria-pressed", String(b.dataset.view === state.view)));

    const week = state.view === "week";
    const isToday = state.day === todayKey();
    if (week) {
      const ws = weekStart();
      $("#day-title").textContent = `${fmtWeekHead.format(dayDate(ws))} – ${fmtWeekHead.format(dayDate(shiftDay(ws, 6)))}`;
      $("#prev").textContent = t("prevWeek"); $("#next").textContent = t("nextWeek"); $("#today").textContent = t("thisWeek");
      $("#prev").title = t("prevWeekT"); $("#next").title = t("nextWeekT");
    } else {
      const d = dayDate(state.day);
      const title = LANG === "zh" ? `${fmtDayTitle.format(d)} · ${fmtDayTitleEn.format(d)}` : fmtDayTitleEn.format(d);
      $("#day-title").textContent = title + (isToday ? t("todaySuffix") : "");
      $("#prev").textContent = "←"; $("#next").textContent = "→"; $("#today").textContent = t("today");
      $("#prev").title = t("prevDayT"); $("#next").title = t("nextDayT");
    }
    $("#today").disabled = week ? weekStart() === (state.weekFromToday ? todayKey() : weekStartOf(todayKey())) : isToday;
    $("#date-input").value = state.day;
    $("#f-film").checked = state.film;
    $("#f-subs").checked = state.subs;
    renderSubsHint();
    $("#f-upcoming").checked = state.upcoming;
    $("#f-specials").checked = state.specials;
    $("#f-upcoming-wrap").hidden = week;
    $("#f-weekstart").checked = state.weekFromToday;
    $("#f-weekstart-wrap").hidden = !week;
    if (document.activeElement !== $("#f-q")) $("#f-q").value = state.q;
  }

  /** With the subtitle filter on, say how many otherwise-visible screenings were hidden as "language unknown". */
  function renderSubsHint() {
    const hint = $("#f-subs-hint");
    if (!state.subs) { hint.textContent = ""; hint.title = ""; return; }
    const days = activeDays();
    const now = new Date();
    let unknown = 0;
    for (const d of days) for (const s of screeningsForDay(d)) {
      if (shown(s.venue_id) && needsNoEnglish(s) === null && passesFilters(s, now, true)) unknown++;
    }
    hint.textContent = unknown ? t("hiddenUnknown", unknown) : "";
    hint.title = unknown ? t("hiddenUnknownT") : "";
  }

  function weekStartOf(day) {
    const dow = dayDate(day).getUTCDay();
    return shiftDay(day, -((dow - 4 + 7) % 7));
  }

  /** Region row (NYC / PHL / LA …): multi-select; hidden when every cinema is in one region. */
  function renderRegions() {
    const box = $("#regions");
    box.hidden = REGIONS.length < 2;
    if (box.hidden) return;
    box.replaceChildren(...REGIONS.map((r) => {
      const on = state.regions.has(r);
      return el("button", {
        class: "chip region" + (on ? " on" : ""), "aria-pressed": String(on),
        onclick: (e) => {
          // a region switched on shows all of its cinemas, even ones switched off earlier; the other
          // regions' cinemas keep their own on / off for when those regions come back
          const withVenuesOf = (regions) => new Set([...state.venues,
            ...activeVenues.filter((v) => regions.has(regionOf(v))).map((v) => v.id)]);
          if (e.target.classList.contains("only")) {
            const only = new Set([r]);
            return update({ regions: only, venues: withVenuesOf(only) });
          }
          const next = new Set(state.regions);
          if (next.has(r)) return next.delete(r), update({ regions: next });   // the last one off leaves none on
          next.add(r);
          update({ regions: next, venues: withVenuesOf(new Set([r])) });
        },
      }, r, el("span", { class: "only", title: t("onlyT") }, t("only")));
    }));
  }

  function renderChips() {
    const counts = {};
    const now = new Date();
    const days = activeDays();
    for (const d of days) for (const s of screeningsForDay(d)) {
      if (passesFilters(s, now)) counts[s.venue_id] = (counts[s.venue_id] || 0) + 1;
    }
    $("#chips").replaceChildren(...venuesInRegions().map((v) => {
      const on = state.venues.has(v.id);
      const problem = v.status === "stale" || v.status === "failed";
      const tip = [
        v.name,
        `${t("chipStatus")}: ${v.status}${isFallback(v.source) ? ` (via ${v.source})` : ""}`,
        v.adapter ? t("dataFrom", v.adapter) : null,
        v.fetched_at ? `${t("chipLastOk")}: ${new Date(v.fetched_at).toLocaleString()}` : t("chipNever"),
        v.horizon_end ? `${t("chipUntil")}: ${v.horizon_end}` : null,
        v.error ? `${t("chipError")}: ${v.error}` : null,
      ].filter(Boolean).join("\n");
      return el("button", {
        class: "chip" + (on ? " on" : ""), style: `--c:${v.color}`, title: tip, "aria-pressed": String(on),
        onclick: (e) => {
          if (e.target.classList.contains("only")) return update({ venues: new Set([v.id]) });
          const next = new Set(state.venues);
          next.has(v.id) ? next.delete(v.id) : next.add(v.id);
          update({ venues: next });
        },
      },
        el("span", { class: "sw" }),
        v.short || v.name,
        el("span", { class: "n" }, counts[v.id] || 0),
        el("span", { class: "only", title: t("onlyT") }, t("only")),
        problem ? el("span", { class: "dot " + v.status }) : isFallback(v.source) ? el("span", { class: "dot ss" }) : null);
    }));
  }

  // ---------- Timeline ----------
  /** Greedy lane packing so overlapping screenings (multi-screen venues) don't collide. */
  function packLanes(items) {
    const lanes = [];
    for (const it of items.sort((a, b) => a.from - b.from || b.to - a.to)) {
      let i = lanes.findIndex((end) => end <= it.from);
      if (i < 0) { i = lanes.length; lanes.push(0); }
      lanes[i] = it.to + 3;
      it.lane = i;
    }
    return Math.max(lanes.length, 1);
  }

  function renderTimeline() {
    const main = $("#main");
    const list = visibleForDay(state.day);
    if (!list.length) return main.replaceChildren(renderEmpty());

    const items = list.map((s) => {
      const tz = tzOf(s);
      const from = minutesInDay(s.start, state.day, tz);
      const known = !!s.runtime_min || !!s.end;
      const to = s.end ? Math.max(minutesInDay(s.end, state.day, tz), from + 15) : from + (s.runtime_min || DEFAULT_RUNTIME);
      return { s, from, to, known };
    });
    // axis: at least 10:00 → 25:00 (1am), widened to fit anything outside
    const t0 = Math.min(600, Math.floor(Math.min(...items.map((i) => i.from)) / 60) * 60);
    const t1 = Math.max(1500, Math.ceil(Math.max(...items.map((i) => i.to)) / 60) * 60);
    const span = t1 - t0;

    const vertical = NARROW.matches;
    const labelW = vertical ? 44 : 160;          // full venue names (wrap to two lines if needed)
    const avail = Math.max(main.clientWidth - labelW - 8, 400);
    const ppm = vertical ? 1.15 : Math.max(1.25, avail / span);       // pixels per minute
    const laneH = vertical ? 78 : 50;                                   // lane thickness

    const byVenue = groupByVenue(list);
    const rows = byVenue.map(([vid]) => {
      const vi = items.filter((i) => i.s.venue_id === vid);
      return { v: venueById[vid], items: vi, lanes: packLanes(vi) };
    });

    // Each row's axis is its cinema's local clock, so "now" sits at a different spot per time zone:
    // one line across the body when all rows share a zone, otherwise a marker inside each row.
    const now = new Date();
    const zones = new Set(rows.map((r) => r.v.timezone || DEFAULT_TZ));
    const nowFor = (tz) => (state.day === todayKey() ? minutesInDay(now.toISOString(), state.day, tz) : null);
    const oneZone = zones.size === 1;
    const nowMin = nowFor(oneZone ? [...zones][0] : VIEWER_TZ);
    const pos = (from, to) => vertical
      ? `top:${(from - t0) * ppm}px;height:${Math.max((to - from) * ppm - 2, 14)}px;`
      : `left:${(from - t0) * ppm}px;width:${Math.max((to - from) * ppm - 2, 14)}px;`;

    const hours = [];
    for (let m = t0; m <= t1; m += 60) hours.push(m);
    const hourLabel = (m) => { const h = (m / 60) % 24; return `${h % 12 || 12}${h < 12 ? "am" : "pm"}`; };

    const axis = el("div", { class: "tl-axis" }, hours.map((m) =>
      el("span", { class: "tl-hour", style: vertical ? `top:${(m - t0) * ppm}px` : `left:${(m - t0) * ppm}px` }, hourLabel(m))));

    const grid = hours.map((m) => el("div", { class: "tl-gridline", style: vertical ? `top:${(m - t0) * ppm}px` : `left:${(m - t0) * ppm}px` }));
    const nowLine = oneZone && nowMin != null && nowMin >= t0 && nowMin <= t1
      ? el("div", { class: "tl-now", style: vertical ? `top:${(nowMin - t0) * ppm}px` : `left:${(nowMin - t0) * ppm}px` }) : null;

    const hl = fold(state.hl);
    const rowEls = rows.map(({ v, items: vi, lanes }) => {
      const blocks = vi.map(({ s, from, to, known, lane }) => {
        const past = new Date(s.start) < now;
        const cls = ["tl-block", known ? "" : "unknown", past ? "past" : "", hl && fold(s.title) === hl ? "hl" : "",
          FILM_FORMATS.has(s.format) ? "onfilm" : ""].filter(Boolean).join(" ");
        const lanePos = vertical ? `left:${lane * laneH}px;width:${laneH - 4}px;` : `top:${lane * laneH + 3}px;height:${laneH - 5}px;`;
        return el("button", {
          class: cls, style: `--c:${v.color};${pos(from, to)}${lanePos}`,
          title: `${timeLabel(s.start, tzOf(s))} ${s.title}${filmMeta(s)}`,
          onclick: (e) => { e.stopPropagation(); showPopover(s, e.currentTarget); },
        },
          el("span", { class: "tl-time" }, timeLabel(s.start, tzOf(s)), s.format && FILM_FORMATS.has(s.format) ? ` · ${s.format}` : ""),
          el("span", { class: "tl-title" }, s.title),
          isFallback(s.source) ? el("span", { class: "tl-via", title: `via ${s.source}` }, s.source.slice(0, 2).toUpperCase()) : null);
      });
      const size = lanes * laneH;
      const rowNow = oneZone ? null : nowFor(v.timezone || DEFAULT_TZ);
      const rowNowEl = rowNow != null && rowNow >= t0 && rowNow <= t1
        ? el("div", { class: "tl-now in-row", style: vertical ? `top:${(rowNow - t0) * ppm}px` : `left:${(rowNow - t0) * ppm}px` }) : null;
      return el("div", { class: "tl-row", style: `--c:${v.color};` + (vertical ? `width:${size}px` : `height:${size}px`) },
        el("div", { class: "tl-label", title: v.name }, el("span", { class: "sw" }),
          el("div", { class: "vwrap" }, el("span", { class: "vname" }, v.name), statusBadge(v))),
        el("div", { class: "tl-track", style: vertical ? `height:${span * ppm}px` : `width:${span * ppm}px` }, grid, blocks, rowNowEl));
    });

    const wrap = el("div", { class: "timeline" + (vertical ? " vertical" : ""), style: `--label-w:${labelW}px` },
      el("div", { class: "tl-inner", style: vertical ? "" : `width:${labelW + span * ppm + 8}px` },
        el("div", { class: "tl-head" }, el("div", { class: "tl-corner" }), axis),
        el("div", { class: "tl-body" }, rowEls, nowLine ? el("div", { class: "tl-now-wrap" }, nowLine) : null)));
    main.replaceChildren(wrap);

    // start scrolled near "now" (today) or the first screening
    const focus = (nowMin ?? Math.min(...items.map((i) => i.from))) - 60;
    if (vertical) {
      const y = wrap.getBoundingClientRect().top + window.scrollY + (focus - t0) * ppm - 120;
      if (nowMin != null && window.scrollY === 0) window.scrollTo({ top: Math.max(0, y) });
    } else {
      wrap.scrollLeft = Math.max(0, (focus - t0) * ppm);
    }
  }

  // ---------- List ----------
  function renderList() {
    const main = $("#main");
    const todays = visibleForDay(state.day);
    if (!todays.length) return main.replaceChildren(renderEmpty());
    const now = new Date();
    const hl = fold(state.hl);
    main.replaceChildren(...groupByVenue(todays).map(([vid, list]) => {
      const v = venueById[vid];
      const films = groupFilms(list);
      return el("section", { class: "venue-group", style: `--c:${v.color}` },
        el("h3", {}, v.website ? el("a", { href: v.website, target: "_blank", rel: "noopener", title: t("website") }, v.name) : v.name,
          el("span", { class: "meta" }, t("filmsShows", films.length, list.length)), statusBadge(v)),
        films.map((f) => el("div", { class: "film" + (hl && fold(f.title) === hl ? " hl" : "") },
          el("div", { class: "times" }, timeLinks(f.showings, now)),
          el("div", { class: "info" },
            link(f.detail_url, "title", f.title),
            el("span", { class: "meta" }, filmMeta(f)),
            f.series ? el("span", { class: "tag series" }, f.series) : null,
            f.note ? el("span", { class: "tag note" }, f.note) : null,
            viaBadge(f)))));
    }));
  }

  /** One link per start time. Twins (the same film starting together on two screens) share one time
   *  marked "×2"; hovering it, or tapping it on a phone, opens one box per screen, each with its own link. */
  function timeLinks(showings, now) {
    const byStart = new Map();
    for (const s of showings) {
      if (!byStart.has(s.start)) byStart.set(s.start, []);
      byStart.get(s.start).push(s);
    }
    return [...byStart.values()].map((group) => {
      const s = group[0];
      const label = timeLabel(s.start, tzOf(s));
      const past = new Date(s.start) < now;
      if (group.length === 1) {
        return s.ticket_url
          ? el("a", { class: past ? "past" : null, href: s.ticket_url, target: "_blank", rel: "noopener" }, label)
          : el("span", { class: past ? "past" : null }, label);
      }
      group.sort((a, b) => (a.screen || "").localeCompare(b.screen || "", undefined, { numeric: true }));
      const menu = el("span", { class: "twin-menu" }, group.map((x, i) =>
        el("a", { href: x.ticket_url || x.detail_url, target: "_blank", rel: "noopener" }, x.screen || t("showingN", i + 1))));
      return el("span", { class: "twin" + (past ? " past" : ""), role: "button", tabindex: "0", "aria-haspopup": "true",
        onclick: (e) => {
          if (e.target.closest(".twin-menu")) return;
          e.stopPropagation();
          const open = !e.currentTarget.classList.contains("open");
          closeTwins();
          e.currentTarget.classList.toggle("open", open);
        } }, label, el("sup", {}, `×${group.length}`), menu);
    });
  }
  const closeTwins = () => document.querySelectorAll(".twin.open").forEach((x) => x.classList.remove("open"));

  /** Days the counters (cinema buttons, "language unknown" hint) cover: every day from today while
   *  searching, else the week or the single day on screen. */
  function activeDays() {
    if (state.q) return dataDays.filter((d) => d >= todayKey());
    return state.view === "week" ? [...Array(7)].map((_, i) => shiftDay(weekStart(), i)) : [state.day];
  }

  function dayHeading(d) {
    const date = dayDate(d);
    const base = LANG === "zh" ? `${fmtDayTitle.format(date)} · ${fmtDayTitleEn.format(date)}` : fmtDayTitleEn.format(date);
    return base + (d === todayKey() ? t("todaySuffix") : d === shiftDay(todayKey(), 1) ? t("tomorrowSuffix") : "");
  }

  // ---------- Search ----------
  /** Typing in the search box leaves the day / week and lists every matching screening from today on,
   *  day by day (title, director and series are matched; the cinema and other filters still apply). */
  function renderSearch() {
    const main = $("#main");
    const now = new Date();
    const groups = [];
    const films = new Set();
    let total = 0;
    for (const d of activeDays()) {
      const list = screeningsForDay(d).filter((s) => shown(s.venue_id) && passesFilters(s, now))
        .sort((a, b) => a.start.localeCompare(b.start) || a.title.localeCompare(b.title));
      if (!list.length) continue;
      groups.push([d, list]);
      total += list.length;
      list.forEach((s) => films.add(`${s.venue_id}|${fold(s.title)}`));
    }
    const head = el("div", { class: "search-head" },
      el("strong", {}, t("searchSummary", state.q, total, films.size)),
      groups.length ? el("span", { class: "meta" }, ` · ${groups[0][0]} – ${groups[groups.length - 1][0]}`) : null,
      el("button", { class: "link-btn", onclick: () => update({ q: "" }) }, t("clearSearch")));
    if (!total) {
      const box = el("div", { class: "empty" }, t("searchNone", state.q));
      if (state.film || state.subs || state.upcoming || state.specials) {
        box.append(el("br"), el("button", { onclick: () => update({ film: false, subs: false, upcoming: false, specials: false }) }, t("clearFilters")));
      }
      return main.replaceChildren(head, box);
    }
    const twinRows = (list) => {
      const rows = new Map();
      for (const s of list) {
        if (!rows.has(twinKey(s))) rows.set(twinKey(s), []);
        rows.get(twinKey(s)).push(s);
      }
      return [...rows.values()];
    };
    main.replaceChildren(head, ...groups.map(([d, list]) => el("section", { class: "search-day" },
      el("h3", {}, dayHeading(d), el("span", { class: "meta" }, ` ${list.length}`)),
      twinRows(list).map((row) => {
        const s = row[0];
        const v = venueById[s.venue_id];
        return el("div", { class: "film" },
          el("div", { class: "times" }, timeLinks(row, now)),
          el("div", { class: "info" },
            el("span", { class: "svenue", style: `--c:${v.color}` }, el("span", { class: "sw" }), v.name),
            el("button", { class: "title as-link", onclick: (e) => { e.stopPropagation(); showPopover(s, e.currentTarget); } }, s.title),
            el("span", { class: "meta" }, filmMeta(s)),
            s.series ? el("span", { class: "tag series" }, s.series) : null,
            s.note ? el("span", { class: "tag note" }, s.note) : null,
            viaBadge(s)));
      }))));
  }

  // ---------- Week ----------
  function renderWeek() {
    const main = $("#main");
    const ws = weekStart();
    const days = [...Array(7)].map((_, i) => shiftDay(ws, i));
    const today = todayKey();
    const venues = activeVenues.filter((v) => shown(v.id));
    if (!venues.length) return main.replaceChildren(renderEmpty());

    const cells = {};             // venue -> day -> Map(title -> {count, film})
    let total = 0;
    for (const d of days) {
      for (const s of screeningsForDay(d)) {
        if (!shown(s.venue_id) || !passesFilters(s)) continue;
        const m = ((cells[s.venue_id] ||= {})[d] ||= new Map());
        const e = m.get(s.title) || { count: 0, onfilm: false, first: s.start };
        e.count++; e.onfilm ||= FILM_FORMATS.has(s.format);
        if (Date.parse(s.start) < Date.parse(e.first)) e.first = s.start;
        m.set(s.title, e);
        total++;
      }
    }
    if (!total) return main.replaceChildren(renderEmpty(t("weekEmpty")));

    const head = el("div", { class: "wk-row wk-head" }, el("div", { class: "wk-venue" }),
      days.map((d) => el("button", {
        class: "wk-day" + (d === today ? " today" : ""), title: t("openDayT"),
        onclick: () => update({ view: "timeline", day: d, hl: "" }),
      }, fmtWeekHead.format(dayDate(d)))));

    const rows = venues.map((v) => {
      const hasData = v.horizon_end && days.some((d) => d <= v.horizon_end);
      return el("div", { class: "wk-row", style: `--c:${v.color}` },
        el("div", { class: "wk-venue" }, el("span", { class: "sw" }),
          el("div", { class: "vwrap" }, el("span", { class: "vname" }, v.name), statusBadge(v))),
        days.map((d) => {
          const m = cells[v.id]?.[d];
          const beyond = v.horizon_end && d > v.horizon_end;
          return el("div", { class: "wk-cell" + (d === today ? " today" : "") + (beyond ? " beyond" : "") },
            m ? [...m.entries()].sort((a, b) => Date.parse(a[1].first) - Date.parse(b[1].first)).map(([title, e]) =>
              el("button", {
                class: "wk-film" + (e.onfilm ? " onfilm" : ""),
                title: t("weekFilmT", title, e.count),
                onclick: () => update({ view: "timeline", day: d, hl: title }),
              }, title, e.count > 1 ? el("span", { class: "n" }, ` ×${e.count}`) : null))
              : el("span", { class: "wk-none" }, beyond || !hasData ? t("notAnnounced") : "—"));
        }));
    });
    main.replaceChildren(el("div", { class: "week" }, el("div", { class: "wk-grid" }, head, rows)));
  }

  // ---------- popover ----------
  function showPopover(s, anchor) {
    const v = venueById[s.venue_id];
    const pop = $("#popover");
    const tz = tzOf(s);
    const endLabel = s.end ? ` – ${timeLabel(s.end, tz)}` : "";
    const zone = tz !== VIEWER_TZ ? ` ${zoneLabel(s.start, tz)}` : "";   // "7:00pm PDT" for another time zone
    const meta = [s.director, s.year, s.runtime_min ? t("minutes", s.runtime_min) : null, s.format, s.language].filter(Boolean).join(" · ");
    pop.replaceChildren(...[
      el("button", { class: "pop-close", "aria-label": t("close"), onclick: hidePopover }, "×"),
      el("div", { class: "pop-venue", style: `--c:${v.color}` }, el("span", { class: "sw" }), v.name, hasTwin(s) && s.screen ? ` · ${s.screen}` : ""),
      el("h4", {}, s.title),
      el("div", { class: "pop-time" }, `${timeLabel(s.start, tz)}${endLabel}${zone}`, s.runtime_min || s.end ? "" : el("span", { class: "muted" }, t("runtimeUnknown"))),
      meta ? el("div", { class: "pop-meta" }, meta) : null,
      s.series ? el("div", {}, el("span", { class: "tag series" }, s.series)) : null,
      s.note ? el("div", { class: "pop-note" }, s.note) : null,
      el("div", { class: "pop-links" },
        s.ticket_url ? el("a", { href: s.ticket_url, target: "_blank", rel: "noopener", class: "btn" }, t("tickets")) : null,
        s.detail_url ? el("a", { href: s.detail_url, target: "_blank", rel: "noopener", class: "btn ghost" }, t("details")) : null,
        CAL ? calendarPicker(s, v) : null,
        viaBadge(s)),
    ].filter(Boolean));
    pop.hidden = false;
    const r = anchor.getBoundingClientRect();
    const pw = Math.min(320, window.innerWidth - 24);
    pop.style.width = pw + "px";
    let left = Math.min(Math.max(12, r.left), window.innerWidth - pw - 12);
    let top = r.bottom + 6;
    if (top + pop.offsetHeight > window.innerHeight - 12) top = Math.max(12, r.top - pop.offsetHeight - 6);
    pop.style.left = left + "px";
    pop.style.top = top + "px";
  }

  function hidePopover() { const p = $("#popover"); if (p) p.hidden = true; }

  // ---------- add to calendar (site/calendar.js) ----------
  const CAL = window.CinemaCalendar;
  const closePickers = () => document.querySelectorAll(".cal-pick.open").forEach((x) => x.classList.remove("open"));

  /** "Add to calendar ▾" beside Tickets / Details: hovering it (or tapping, on a phone) opens Apple / Google. */
  function calendarPicker(s, v) {
    const placeMenu = (pick) => {     // open upwards when there is no room below
      const r = pick.getBoundingClientRect();
      pick.classList.toggle("up", r.bottom + 90 > window.innerHeight);
    };
    const pick = el("span", { class: "cal-pick", onmouseenter: (e) => placeMenu(e.currentTarget) },
      el("button", { type: "button", class: "btn ghost", "aria-haspopup": "true",
        onclick: (e) => {
          e.stopPropagation();
          const open = !pick.classList.contains("open");
          closePickers();
          placeMenu(pick);
          pick.classList.toggle("open", open);
        } }, t("addCal"), el("span", { class: "caret" }, "▾")),
      el("span", { class: "cal-menu", role: "menu" },
        el("button", { type: "button", role: "menuitem", title: t("addCalT"),
          onclick: (e) => { e.stopPropagation(); pick.classList.remove("open"); addToCalendar(s, pick); } }, t("appleCal")),
        el("a", { role: "menuitem", title: t("googleCalT"), target: "_blank", rel: "noopener",
          href: CAL.googleUrl(CAL.eventFor(s, v, LANG), CAL.isMobile()), onclick: () => pick.classList.remove("open") }, t("googleCal"))));
    return pick;
  }

  function addToCalendar(s, btn) {
    const note = (msg) => {
      const links = btn.closest(".pop-links");
      const old = links.nextElementSibling;
      if (old && old.classList.contains("pop-cal-note")) old.remove();
      links.after(el("div", { class: "pop-cal-note muted" }, msg));
    };
    if (CAL.iosNeedsSafari()) return note(t("calSafari"));
    CAL.download(CAL.toICS(CAL.eventFor(s, venueById[s.venue_id], LANG)), CAL.fileName(s));
    if (!CAL.isIOS()) note(t("calSaved"));     // iOS Safari shows Calendar's own "Add" sheet
  }

  // ---------- empty / footer ----------
  function renderEmpty(msg) {
    const box = el("div", { class: "empty" });
    if (!DATA.generated_at) {
      box.append(t("noData")[0], el("code", {}, "python -m scraper.run"), t("noData")[1]);
      return box;
    }
    if (!state.venues.size || !state.regions.size) {
      box.append(t("noVenues"), el("button", { onclick: selectAll }, t("selectAll")));
      return box;
    }
    box.append(msg || t("dayEmpty"));
    if (state.film || state.subs || state.q || state.upcoming || state.specials) {
      box.append(el("br"), el("button", { onclick: () => update({ film: false, subs: false, q: "", upcoming: false, specials: false }) }, t("clearFilters")));
    }
    if (state.view !== "week") {
      const hasSel = (d) => screeningsForDay(d).some((s) => shown(s.venue_id) && passesFilters(s));
      const prev = [...dataDays].reverse().find((d) => d < state.day && hasSel(d));
      const next = dataDays.find((d) => d > state.day && hasSel(d));
      if (prev || next) box.append(el("br"));
      if (prev) box.append(el("button", { onclick: () => update({ day: prev }) }, `← ${prev}`));
      if (next) box.append(el("button", { onclick: () => update({ day: next }) }, `${next} →`));
    }
    return box;
  }

  function renderFooter() {
    const disabled = DATA.venues.filter((v) => v.status === "disabled").map((v) => v.name);
    const range = dataDays.length ? t("range", dataDays[0], dataDays[dataDays.length - 1]) : "";
    $("#footer").textContent = [
      t("total", DATA.screenings.length), range,
      disabled.length ? t("disabled", disabled) : "",
      t("dashedNote"),
    ].filter(Boolean).join(" · ");
    $("#footer").append(el("div", { class: "credits" },
      t("credits")[0],
      el("a", { href: "https://www.themoviedb.org/", target: "_blank", rel: "noopener" }, "TMDB"),
      t("credits")[1],
      el("a", { href: "https://github.com/Marc506/corridor-showtimes", target: "_blank", rel: "noopener" }, t("source"))));
  }

  // ---------- "add your cinemas" guide ----------
  function openGuide() {
    const dlg = $("#customize-dialog");
    const readme = LANG === "zh" ? `${REPO}/blob/main/README.zh-CN.md#自定义影院` : `${REPO}#add-your-own-cinemas`;
    const copyBtn = el("button", { class: "copy-btn", type: "button", onclick: async (e) => {
      try { await navigator.clipboard.writeText(t("guidePrompt")); e.target.textContent = t("copied"); } catch (_) { /* select manually */ }
    } }, t("copy"));
    const steps = t("guideSteps").map(([head, body], i) => el("li", {},
      el("strong", {}, head), " ",
      body ?? el("div", { class: "prompt" }, el("code", {}, t("guidePrompt")), copyBtn),
      i === 1 ? el("div", {}, el("a", { href: REPO, target: "_blank", rel: "noopener" }, `${t("guideGithub")} ↗`)) : null));
    dlg.replaceChildren(
      el("button", { class: "pop-close", type: "button", "aria-label": t("close"), onclick: () => dlg.close() }, "×"),
      el("h3", { id: "guide-title" }, t("guideTitle")),
      el("p", {}, t("guideIntro")),
      el("ol", {}, steps),
      el("p", { class: "guide-links" }, el("a", { href: readme, target: "_blank", rel: "noopener" }, `${t("guideFull")} ↗`)),
      el("p", { class: "muted" }, t("guideHelp"), " ",
        el("a", { href: `${REPO}/issues/new?template=help-add-cinema.yml`, target: "_blank", rel: "noopener" }, `${t("guideHelpLink")} ↗`)));
    if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
  }

  function selectAll() { update({ venues: new Set(activeVenues.map((v) => v.id)), regions: new Set(REGIONS) }); }

  // ---------- wiring ----------
  function step(n) {
    const days = state.view === "week" ? 7 * n : n;
    update({ day: shiftDay(state.day, days), hl: "" });
  }

  /** If the page was showing "today" and the date has changed since (midnight, or resumed from the
   *  background), move to the new today. Returns true if it re-rendered. */
  let shownToday = todayKey();
  function followToday() {
    const now = todayKey();
    if (now === shownToday) return false;
    const wasOnToday = state.day === shownToday;
    shownToday = now;
    if (!wasOnToday) return false;
    update({ day: now, hl: "" });
    return true;
  }

  function init() {
    readHash();
    writeHash();
    $("#prev").addEventListener("click", () => step(-1));
    $("#next").addEventListener("click", () => step(1));
    $("#today").addEventListener("click", () => update({ day: todayKey(), hl: "" }));
    $("#date-input").addEventListener("change", (e) => validDay(e.target.value) && update({ day: e.target.value, hl: "" }));
    $("#select-all").addEventListener("click", selectAll);
    $("#customize").addEventListener("click", openGuide);
    $("#customize-dialog").addEventListener("click", (e) => { if (e.target.id === "customize-dialog") e.target.close(); });
    $("#lang-toggle").addEventListener("click", () => setLang(LANG === "zh" ? "en" : "zh"));
    document.querySelectorAll("#views button").forEach((b) =>
      b.addEventListener("click", () => update({ view: b.dataset.view })));
    $("#f-film").addEventListener("change", (e) => update({ film: e.target.checked }));
    $("#f-subs").addEventListener("change", (e) => update({ subs: e.target.checked }));
    $("#f-upcoming").addEventListener("change", (e) => update({ upcoming: e.target.checked }));
    $("#f-specials").addEventListener("change", (e) => update({ specials: e.target.checked }));
    $("#f-weekstart").addEventListener("change", (e) => update({ weekFromToday: e.target.checked }));
    let qTimer;
    $("#f-q").addEventListener("input", (e) => {
      clearTimeout(qTimer);
      qTimer = setTimeout(() => update({ q: e.target.value.trim() }), 150);
    });
    window.addEventListener("hashchange", () => { readHash(); render(); });
    document.addEventListener("click", (e) => {
      if (!e.target.closest("#popover")) hidePopover();
      if (!e.target.closest(".twin")) closeTwins();
      if (!e.target.closest(".cal-pick")) closePickers();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && e.target === $("#f-q") && state.q) { e.target.value = ""; e.target.blur(); return update({ q: "" }); }
      if (e.key === "Escape") return hidePopover();
      if (e.target.matches("input, textarea") || e.metaKey || e.ctrlKey || e.altKey || state.q) return;
      if (e.key === "ArrowLeft") step(-1);
      if (e.key === "ArrowRight") step(1);
    });
    let resizeTimer;
    const rerender = () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => state.view === "timeline" && render(), 150); };
    window.addEventListener("resize", rerender);
    NARROW.addEventListener("change", rerender);
    // sticky sub-headers (week day row) sit just below the sticky page header
    const top = document.querySelector(".top");
    const setHeaderH = () => document.documentElement.style.setProperty("--header-h", top.offsetHeight + "px");
    if (window.ResizeObserver) new ResizeObserver(setHeaderH).observe(top);
    setHeaderH();
    render();
    setInterval(() => { followToday() || renderHeader(); }, 60e3);   // keep "updated x min ago" fresh
    // Coming back to a tab / home-screen app: roll over to the new day, and after a long absence
    // reload so the page picks up the data refreshed in the meantime.
    let hiddenAt = null;
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) { hiddenAt = Date.now(); return; }
      if (hiddenAt && Date.now() - hiddenAt > 60 * 60e3) return location.reload();
      hiddenAt = null;
      followToday();
    });
    window.addEventListener("pageshow", (e) => { if (e.persisted) followToday(); });
  }

  init();
})();
