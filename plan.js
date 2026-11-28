/* Corridor Showtimes — the planner's solver (PLANNER.md). Given the films someone wants to see and a range of
 * days and cinemas, pick at most one screening per film so that no two overlap and the changes between
 * cinemas are comfortable; offer up to three plans (relaxed / fewest days / early nights) and, when not every
 * film fits, the fallbacks of §3.5 (drop a different film; miss a few minutes of a head or tail).
 *
 * Pure functions, no DOM: planner.js runs them in a Web Worker (built from this file's own source, so it also
 * works when the page is opened from disk), and tests/test_plan.py runs them under Node.
 *
 * How it solves. Screenings are grouped by day ("blocks"; two days share a block only when a late show runs
 * into the next day's first one). Inside a block a dynamic programme over (films used, last screening) finds,
 * for every set of films, the best chain of screenings; across blocks those sets are combined by a subset DP
 * over every set of films — exact up to 12 films — or, beyond that or past the time limit, by a beam that
 * keeps the 300 best sets after each block (and at most 300 states per screening inside a block).
 *
 * A plan's score is compared lexicographically (§3.3): films covered (more is better), minutes of overlap
 * (only in the fallback that allows it), tight changes, the comfort penalty of the gaps, days used, and how
 * late the last show of a day ends (minutes after that day's local midnight).
 */
(function (root) {
  "use strict";

  function factory() {
    const MIN = 60e3;
    const DEFAULT_TZ = "America/New_York";
    const FILM_FORMATS = new Set(["16mm", "35mm", "70mm", "Film"]);   // as app.js: "Film" = on film, gauge unknown
    const DEFAULTS = {
      tightMin: 15,                 // a change between two cinemas shorter than this is "tight"
      sameVenueTightMin: 10,        // … within one cinema
      forbidTight: false,           // true: a tight change counts as a conflict
      crossRegionMin: 180,          // same day, another region (NYC → PHL): at least this many minutes apart
      maxOverlap: 15,               // the "miss a few minutes" fallback: at most this much overlap (0 = off)
      maxPerDay: null,              // at most this many screenings a day
      unknownRuntimeMin: 120,       // a screening with no end and no runtime is taken as this long
      exactMaxFilms: 12,            // exact up to this many films …
      exactMaxWork: 4e6,            // … and while 2^films × screenings stays under this
      beamWidth: 300,
      timeoutMs: 2000,              // past this the exact solve gives way to the beam
      locked: [], excluded: [],     // screening ids
    };
    const MAX_FILMS = 30;           // masks are 32-bit integers
    const NO_END = -1e9;            // "lastEnd" of an empty plan

    // score components (lexicographic, smaller is better)
    const F = 0, OV = 1, TI = 2, PE = 3, DA = 4, LE = 5;
    const ORDERS = {
      relaxed: [F, OV, TI, PE, DA, LE],
      compact: [F, OV, DA, TI, PE, LE],
      early: [F, OV, LE, TI, PE, DA],
    };
    const OBJECTIVES = ["relaxed", "compact", "early"];

    // ---------- film identity (§2.1) ----------
    const fold = (s) => String(s || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
    /** Accents, case and punctuation removed: "Le Samouraï!" → "le samourai". */
    const plain = (s) => fold(s).replace(/&/g, " and ").replace(/[^\p{L}\p{N}]+/gu, " ").trim();

    function titleKey(s) {
      const t = plain(s.title);
      return s.year ? `${t}|${s.year}` : `${t}||${plain(s.director)}`;
    }

    /** screening id → film key. An IMDb id when there is one; otherwise title | year (title | | director
     *  without a year) — joined to an IMDb id when exactly one film with that title and year has one. Computed
     *  over every screening, so a key doesn't depend on the days or cinemas chosen. */
    function filmKeys(screenings) {
      const imdbs = new Map();
      for (const s of screenings) {
        if (!s.imdb_id) continue;
        const k = titleKey(s);
        if (!imdbs.has(k)) imdbs.set(k, new Set());
        imdbs.get(k).add(s.imdb_id);
      }
      const out = new Map();
      for (const s of screenings) {
        let key;
        if (s.imdb_id) key = "i:" + s.imdb_id;
        else {
          const k = titleKey(s), ids = imdbs.get(k);
          key = ids && ids.size === 1 ? "i:" + [...ids][0] : "t:" + k;
        }
        out.set(s.id, key);
      }
      return out;
    }

    /** A short stable id for a film key (share links): FNV-1a, base 36. */
    function filmId(key) {
      let h = 0x811c9dc5;
      for (const ch of String(key)) { h ^= ch.codePointAt(0); h = Math.imul(h, 0x01000193) >>> 0; }
      return h.toString(36);
    }

    const mostCommon = (xs) => {
      const n = new Map();
      for (const x of xs) if (x != null && x !== "") n.set(x, (n.get(x) || 0) + 1);
      let best = null, bn = 0;
      for (const [x, c] of n) if (c > bn) { best = x; bn = c; }
      return best;
    };

    /** Candidate screenings → films: {key, id, title, director, year, runtime_min, language, formats, venues,
     *  days, showings}, in title order. */
    function groupFilms(showings) {
      const by = new Map();
      for (const s of showings) {
        if (!by.has(s.filmKey)) by.set(s.filmKey, []);
        by.get(s.filmKey).push(s);
      }
      const films = [...by.entries()].map(([key, list]) => {
        const src = list.map((x) => x.source);
        return {
          key, id: filmId(key),
          title: mostCommon(src.map((s) => s.title)) || src[0].title,
          director: mostCommon(src.map((s) => s.director)),
          year: mostCommon(src.map((s) => s.year)),
          runtime_min: mostCommon(src.map((s) => s.runtime_min)),
          language: mostCommon(src.map((s) => s.language)),
          formats: [...new Set(src.map((s) => s.format).filter(Boolean))],
          venues: [...new Set(list.map((x) => x.venue_id))],
          days: [...new Set(list.map((x) => x.day))].sort(),
          showings: list,
        };
      });
      return films.sort((a, b) => plain(a.title).localeCompare(plain(b.title)) || a.key.localeCompare(b.key));
    }

    // ---------- candidates (§2.2) ----------
    const fmtCache = new Map();
    function fmts(tz) {
      if (!fmtCache.has(tz)) {
        fmtCache.set(tz, {
          day: new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }),
          hm: new Intl.DateTimeFormat("en-US", { timeZone: tz, hour: "numeric", minute: "numeric", hourCycle: "h23" }),
        });
      }
      return fmtCache.get(tz);
    }
    /** Minutes after local midnight of `day` in time zone `tz` (past 1440 for an after-midnight show). */
    function minutesInDay(ms, day, tz) {
      const f = fmts(tz);
      const [h, m] = f.hm.format(ms).split(":").map(Number);
      const d = f.day.format(ms);
      return h * 60 + m + (d > day ? 1440 : d < day ? -1440 : 0);
    }
    const hhmm = (x) => { const m = /^(\d{1,2}):(\d{2})$/.exec(x || ""); return m ? +m[1] * 60 + +m[2] : null; };

    /** true = subtitled / captioned / silent, false = English, null = unknown (as app.js). */
    function needsNoEnglish(s) {
      if (/open caption|\bsubtitled\b/i.test(s.note || "")) return true;
      if (!s.language) return null;
      return s.language.split(",")[0].trim().toLowerCase() !== "english";
    }

    /** The screenings in scope, one per film, cinema and start time (two screens showing a film together count
     *  once), by start. scope: {from, to, venues (ids; null = every cinema), film, subs, specials, now (ms; earlier
     *  starts are left out), dayWindow: {earliest, latest} "HH:MM" | null, unknownRuntimeMin}. */
    function candidates(data, keyOf, scope) {
      const sc = scope || {};
      const venueById = new Map((data.venues || []).map((v) => [v.id, v]));
      const allowed = sc.venues ? new Set(sc.venues) : null;
      const unknown = sc.unknownRuntimeMin || DEFAULTS.unknownRuntimeMin;
      const win = sc.dayWindow ? { a: hhmm(sc.dayWindow.earliest), b: hhmm(sc.dayWindow.latest) } : null;
      if (win && win.a != null && win.b != null && win.b <= win.a) win.b += 1440;     // "11:00 – 01:00"
      const out = [];
      const seen = new Set();
      for (const s of data.screenings || []) {
        if (sc.from && s.day < sc.from) continue;
        if (sc.to && s.day > sc.to) continue;
        const v = venueById.get(s.venue_id);
        if (!v || v.status === "disabled" || (allowed && !allowed.has(v.id))) continue;
        if (sc.film && !FILM_FORMATS.has(s.format)) continue;
        if (sc.subs && needsNoEnglish(s) !== true) continue;
        if (sc.specials && s.run) continue;
        const start = Date.parse(s.start);
        if (isNaN(start) || (sc.now != null && start < sc.now)) continue;
        let end = s.end ? Date.parse(s.end) : NaN;
        let endKnown = end > start;
        if (!endKnown && s.runtime_min > 0) { end = start + s.runtime_min * MIN; endKnown = true; }
        if (!endKnown) end = start + unknown * MIN;
        const filmKey = (keyOf && keyOf.get(s.id)) || "t:" + titleKey(s);
        const twin = `${v.id}|${start}|${filmKey}`;
        if (seen.has(twin)) continue;
        seen.add(twin);
        const tz = v.timezone || DEFAULT_TZ;
        const startMin = minutesInDay(start, s.day, tz);
        const endMin = startMin + Math.round((end - start) / MIN);
        if (win && ((win.a != null && startMin < win.a) || (win.b != null && endMin > win.b))) continue;
        out.push({
          id: s.id, filmKey, venue_id: v.id, region: v.region || v.city || "", day: s.day,
          start, end, endKnown, startMin, endMin, tz,
          screen: s.screen || null, ticket_url: s.ticket_url || null, detail_url: s.detail_url || null, source: s,
        });
      }
      return out.sort(byStart);
    }
    const byStart = (a, b) => a.start - b.start || a.end - b.end || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);

    // ---------- feasibility and score (§3.2, §3.3) ----------
    function params(p) {
      const P = Object.assign({}, DEFAULTS, p || {});
      P.maxOverlap = Math.max(0, Math.min(30, +P.maxOverlap || 0));
      P.maxPerDay = P.maxPerDay > 0 ? Math.min(15, Math.floor(P.maxPerDay)) : null;
      return P;
    }

    /** Can screening b follow screening a (a starts first)? null = no; otherwise the change between them.
     *  `overlap` = true lets two screenings on the same day in one region overlap by up to P.maxOverlap
     *  minutes when both runtimes are known (§3.5, fallback 2). */
    function link(a, b, P, overlap) {
      if (b.start <= a.start) return null;
      const gap = (b.start - a.end) / MIN;
      if (a.day !== b.day) return gap >= 0 ? { sameDay: false, gap, kind: null, tight: false, overlap: 0 } : null;
      const kind = a.venue_id === b.venue_id ? "same-venue" : a.region === b.region ? "same-region" : "cross-region";
      if (kind === "cross-region") return gap >= P.crossRegionMin ? { sameDay: true, gap, kind, tight: false, overlap: 0 } : null;
      if (gap < 0) {
        if (!overlap || !P.maxOverlap || !a.endKnown || !b.endKnown || b.end <= a.end) return null;
        const o = Math.ceil(-gap - 1e-9);
        // each film must be long enough to lose a head and a tail of up to maxOverlap
        if (o > P.maxOverlap || a.end - a.start <= 2 * P.maxOverlap * MIN || b.end - b.start <= 2 * P.maxOverlap * MIN) return null;
        return { sameDay: true, gap, kind, tight: false, overlap: o };
      }
      const tight = gap < (kind === "same-venue" ? P.sameVenueTightMin : P.tightMin);
      if (tight && P.forbidTight) return null;
      return { sameDay: true, gap, kind, tight, overlap: 0 };
    }

    /** The comfort penalty of a gap of g minutes between two screenings on one day (§3.3): short gaps cost
     *  convexly up to 45 minutes; past 4 hours each further hour costs a little. */
    function comfort(g) {
      const x = Math.max(0, g);
      const short = Math.max(0, 45 - x) / 45;
      return short * short * 10 + Math.max(0, x - 240) / 60;
    }

    function cmp(a, b, order) {
      for (const i of order) {
        const d = a[i] - b[i];
        if (i === PE ? Math.abs(d) > 1e-9 : d !== 0) return d < 0 ? -1 : 1;
      }
      return 0;
    }
    function cmpAt(a, ai, b, bi, order) {
      for (const i of order) {
        const d = a[ai + i] - b[bi + i];
        if (i === PE ? Math.abs(d) > 1e-9 : d !== 0) return d < 0 ? -1 : 1;
      }
      return 0;
    }
    const popcount = (x) => { let n = 0; for (let v = x >>> 0; v; v &= v - 1) n++; return n; };

    const TIMEOUT = { timeout: true };
    function clockUntil(deadline) {
      let n = 0;
      return () => { if (deadline !== Infinity && ++n % 64 === 0 && Date.now() > deadline) throw TIMEOUT; };
    }

    // ---------- preparation ----------
    /** The chosen films' candidates after `excluded` and `locked` (a locked screening is the only candidate
     *  of its film, and the film must be in the plan), split into blocks of days. */
    function prepare(showings, films, P) {
      const keys = [...new Set(films)];
      if (keys.length > MAX_FILMS) throw new Error(`at most ${MAX_FILMS} films`);
      const idx = new Map(keys.map((f, i) => [f, i]));
      const excluded = new Set(P.excluded || []);
      const locked = new Set(P.locked || []);
      const lockOf = new Map();
      for (const s of showings) {
        if (locked.has(s.id) && idx.has(s.filmKey) && !excluded.has(s.id) && !lockOf.has(s.filmKey)) lockOf.set(s.filmKey, s.id);
      }
      const all = keys.map(() => 0);                          // candidates per film before exclusions
      const byFilm = keys.map(() => []);
      const nodes = [];
      for (const s of showings) {
        const fi = idx.get(s.filmKey);
        if (fi == null) continue;
        all[fi]++;
        if (excluded.has(s.id)) continue;
        const lk = lockOf.get(s.filmKey);
        if (lk && lk !== s.id) continue;
        const n = { s, fi, bit: (1 << fi) >>> 0, id: s.id, filmKey: s.filmKey, venue_id: s.venue_id, region: s.region,
          day: s.day, start: s.start, end: s.end, endKnown: s.endKnown, endMin: s.endMin };
        nodes.push(n);
        byFilm[fi].push(n);
      }
      nodes.sort(byStart);
      let lockedMask = 0;
      for (const f of lockOf.keys()) lockedMask = (lockedMask | (1 << idx.get(f))) >>> 0;
      // blocks: days in order; a day joins the previous block only when a screening of that block ends after
      // this day's first start
      const days = new Map();
      for (const n of nodes) {
        if (!days.has(n.day)) days.set(n.day, []);
        days.get(n.day).push(n);
      }
      const blocks = [];
      let cur = null, curEnd = -Infinity;
      for (const d of [...days.keys()].sort()) {
        const list = days.get(d);
        const first = Math.min(...list.map((n) => n.start));
        if (cur && first < curEnd) cur.push(...list);
        else { cur = [...list]; blocks.push(cur); curEnd = -Infinity; }
        curEnd = Math.max(curEnd, ...list.map((n) => n.end));
      }
      blocks.forEach((b) => b.sort(byStart));
      return { keys, idx, k: keys.length, n: nodes.length, nodes, byFilm, all, blocks, lockedMask, lockOf };
    }

    // ---------- inside a block: DP over (films used, last screening) ----------
    /** Every non-dominated chain in the block, as states {mask, i, c (score), cnt (screenings that day),
     *  head (minutes of this screening's head overlapped), prev}. `cap` > 0 keeps at most that many states
     *  per last screening (the beam). */
    function blockStates(nodes, P, overlap, cap, tick) {
      const m = nodes.length;
      const perDay = !!P.maxPerDay && nodes[0].day !== nodes[m - 1].day;
      const keyOf = (mask, i, head, cnt) => ((mask * m + i) * 32 + head) * 16 + (perDay ? cnt : 0);
      const layers = nodes.map(() => new Map());
      for (let i = 0; i < m; i++) {
        const n = nodes[i];
        layers[i].set(keyOf(n.bit, i, 0, 1), { mask: n.bit, i, node: n, c: [-1, 0, 0, 0, 1, n.endMin], cnt: 1, head: 0, prev: null });
      }
      const finals = [];
      for (let i = 0; i < m; i++) {
        tick();
        let list = [...layers[i].values()];
        layers[i] = null;
        if (cap && list.length > cap) list = list.sort((x, y) => cmp(x.c, y.c, ORDERS.relaxed)).slice(0, cap);
        const a = nodes[i];
        for (const st of list) {
          finals.push(st);
          for (let j = i + 1; j < m; j++) {
            const b = nodes[j];
            if (st.mask & b.bit) continue;
            const ln = link(a, b, P, overlap);
            if (!ln || (ln.overlap && st.head + ln.overlap > P.maxOverlap)) continue;
            const cnt = ln.sameDay ? st.cnt + 1 : 1;
            if (P.maxPerDay && cnt > P.maxPerDay) continue;
            const c = st.c;
            const nc = [c[F] - 1, c[OV] + ln.overlap, c[TI] + (ln.tight ? 1 : 0), c[PE] + (ln.sameDay ? comfort(ln.gap) : 0),
              c[DA] + (ln.sameDay ? 0 : 1), Math.max(c[LE], b.endMin)];
            const mask = (st.mask | b.bit) >>> 0;
            const key = keyOf(mask, j, ln.overlap, cnt);
            const old = layers[j].get(key);
            if (!old || cmp(nc, old.c, ORDERS.relaxed) < 0) layers[j].set(key, { mask, i: j, node: b, c: nc, cnt, head: ln.overlap, prev: st });
          }
        }
      }
      return finals;
    }

    /** The best chain for each set of films, by `order`; `maxEnd` drops chains ending later than that. */
    function bestBySet(finals, order, maxEnd = Infinity) {
      const best = new Map();
      for (const st of finals) {
        if (st.c[LE] > maxEnd) continue;
        const old = best.get(st.mask);
        if (!old || cmp(st.c, old.c, order) < 0) best.set(st.mask, st);
      }
      return best;
    }

    const chain = (st) => { const out = []; for (let x = st; x; x = x.prev) out.push(x); return out.reverse(); };

    // ---------- across blocks ----------
    /** Exact: the best plan for every set of films, block by block (a subset DP). */
    function combineExact(k, bests, order, tick) {
      const N = 1 << k, W = 6;
      let has = new Uint8Array(N), C = new Float64Array(N * W);
      has[0] = 1; C[LE] = NO_END;
      const parents = [];
      const tmp = new Float64Array(W);
      for (const best of bests) {
        const arr = new Array(N);
        const subs = [];
        let bm = 0;
        for (const [sub, st] of best) { arr[sub] = st; subs.push(sub); bm |= sub; }
        const nh = has.slice(), nC = C.slice(), par = new Int32Array(N);
        for (let mask = 0; mask < N; mask++) {
          if (!has[mask]) continue;
          tick();
          const o = mask * W;
          const relax = (sub) => {
            const c = arr[sub].c;
            tmp[F] = C[o + F] + c[F]; tmp[OV] = C[o + OV] + c[OV]; tmp[TI] = C[o + TI] + c[TI];
            tmp[PE] = C[o + PE] + c[PE]; tmp[DA] = C[o + DA] + c[DA]; tmp[LE] = Math.max(C[o + LE], c[LE]);
            const t = mask | sub, to = t * W;
            if (!nh[t] || cmpAt(tmp, 0, nC, to, order) < 0) { nC.set(tmp, to); nh[t] = 1; par[t] = sub; }
          };
          const free = ~mask & bm;
          if (subs.length <= 1 << popcount(free)) { for (const sub of subs) if (!(sub & mask)) relax(sub); }
          else for (let sub = free; sub; sub = (sub - 1) & free) if (arr[sub]) relax(sub);
        }
        parents.push(par);
        has = nh; C = nC;
      }
      return {
        /** The best set containing `req`, or -1. */
        pick(req, ord = order) {
          let best = -1;
          for (let mask = 0; mask < N; mask++) {
            if (!has[mask] || (mask & req) !== req) continue;
            if (best < 0 || cmpAt(C, mask * W, C, best * W, ord) < 0) best = mask;
          }
          return best;
        },
        score: (mask) => Array.from(C.subarray(mask * W, mask * W + W)),
        legs(mask) {
          const out = [];
          for (let b = bests.length - 1; b >= 0; b--) {
            const sub = parents[b][mask];
            if (!sub) continue;
            out.push(...chain(bests[b].get(sub)));
            mask ^= sub;
          }
          return out.map((st) => st.node).sort(byStart);
        },
      };
    }

    /** Approximate: after each block keep the `width` best sets. */
    function combineBeam(bests, order, width, tick) {
      let beam = [{ mask: 0, c: [0, 0, 0, 0, 0, NO_END], prev: null, st: null }];
      for (const best of bests) {
        const subs = [...best.values()];
        const next = new Map(beam.map((e) => [e.mask, e]));
        for (const e of beam) {
          tick();
          for (const st of subs) {
            if (e.mask & st.mask) continue;
            const c = [e.c[F] + st.c[F], e.c[OV] + st.c[OV], e.c[TI] + st.c[TI], e.c[PE] + st.c[PE], e.c[DA] + st.c[DA], Math.max(e.c[LE], st.c[LE])];
            const mask = (e.mask | st.mask) >>> 0;
            const old = next.get(mask);
            if (!old || cmp(c, old.c, order) < 0) next.set(mask, { mask, c, prev: e, st });
          }
        }
        beam = [...next.values()].sort((x, y) => cmp(x.c, y.c, order)).slice(0, width);
      }
      const byMask = new Map(beam.map((e) => [e.mask, e]));
      return {
        pick(req, ord = order) {
          let best = null;
          for (const e of beam) if ((e.mask & req) === req && (!best || cmp(e.c, best.c, ord) < 0)) best = e;
          return best ? best.mask : -1;
        },
        score: (mask) => byMask.get(mask).c.slice(),
        legs(mask) {
          const out = [];
          for (let e = byMask.get(mask); e && e.st; e = e.prev) out.push(...chain(e.st));
          return out.map((st) => st.node).sort(byStart);
        },
      };
    }

    // ---------- plans ----------
    function describe(objective, legNodes, prep, P, overlap) {
      const legs = legNodes.map((n) => n.s);
      const gaps = [];
      let minGap = null, tightCount = 0, overlapMinutes = 0, overlapCount = 0, pen = 0;
      for (let i = 1; i < legs.length; i++) {
        const a = legs[i - 1], b = legs[i];
        if (a.day !== b.day) continue;
        const gap = (b.start - a.end) / MIN;
        const kind = a.venue_id === b.venue_id ? "same-venue" : a.region === b.region ? "same-region" : "cross-region";
        const ov = gap < 0 ? Math.ceil(-gap - 1e-9) : 0;
        const tight = !ov && kind !== "cross-region" && gap < (kind === "same-venue" ? P.sameVenueTightMin : P.tightMin);
        gaps.push({ from: a.id, to: b.id, minutes: Math.round(gap), kind, tight, overlap: ov });
        if (ov) { overlapMinutes += ov; overlapCount++; } else minGap = minGap == null ? Math.round(gap) : Math.min(minGap, Math.round(gap));
        if (tight) tightCount++;
        pen += comfort(gap);
      }
      const covered = new Set(legs.map((s) => s.filmKey));
      const uncovered = prep.keys.filter((f) => !covered.has(f)).map((f) => whyNot(f, legNodes, prep, P, overlap));
      return {
        objective, legs, covered: [...covered], uncovered, gaps,
        unknownRuntime: legs.filter((s) => !s.endKnown).map((s) => s.id),
        stats: {
          films: legs.length, of: prep.k, days: new Set(legs.map((s) => s.day)).size,
          minGap, tightCount, overlapMinutes, overlapCount, comfort: Math.round(pen * 100) / 100,
          firstStart: legs.length ? legs[0].start : null,
          lastEnd: legs.length ? Math.max(...legs.map((s) => s.end)) : null,
          lastEndMin: legs.length ? Math.max(...legs.map((s) => s.endMin)) : null,
        },
      };
    }

    /** Why a film isn't in the plan: "none" (no screening in range), "excluded" (every one excluded),
     *  "conflict" (each clashes with a screening in the plan — `with` lists those films), "limit" (one fits
     *  beside every screening in the plan but the per-day limit or the beam left it out). */
    function whyNot(filmKey, legNodes, prep, P, overlap) {
      const fi = prep.idx.get(filmKey);
      const cands = prep.byFilm[fi];
      if (!cands.length) return { filmKey, reason: prep.all[fi] ? "excluded" : "none", count: 0 };
      const fits = (a, b) => !!(a.start < b.start ? link(a, b, P, overlap) : link(b, a, P, overlap));
      const blockers = new Set();
      let free = false;
      for (const x of cands) {
        const bl = legNodes.filter((l) => !fits(l, x));
        if (!bl.length) free = true;
        for (const l of bl) blockers.add(l.filmKey);
      }
      return {
        filmKey, reason: free ? "limit" : "conflict", count: cands.length,
        only: cands.length === 1 ? cands[0].id : null, with: [...blockers],
      };
    }

    const legKey = (plan) => plan.legs.map((s) => s.id).join(",");

    /** Strict solve (no overlap): the three objective plans and the "drop another film" alternatives. */
    function solveStrict(prep, P, approx, tick) {
      const cap = approx ? P.beamWidth : 0;
      const finals = prep.blocks.map((b) => blockStates(b, P, false, cap, tick));
      const combine = (order, maxEnd) => {
        const bests = finals.map((f) => bestBySet(f, order, maxEnd));
        return approx ? combineBeam(bests, order, P.beamWidth, tick) : combineExact(prep.k, bests, order, tick);
      };
      const req = prep.lockedMask;
      const tables = {};
      const picks = {};
      tables.relaxed = combine(ORDERS.relaxed);
      picks.relaxed = tables.relaxed.pick(req);
      if (picks.relaxed < 0) return { lockConflict: true, plans: [], drop: [], maxFilms: 0 };
      tables.compact = combine(ORDERS.compact);
      picks.compact = tables.compact.pick(req);
      if (approx) {
        tables.early = combine(ORDERS.early);
        picks.early = tables.early.pick(req);
      } else {
        // the latest end is a maximum, not a sum: find the earliest achievable, then optimise the rest under it
        const first = combine(ORDERS.early);
        const L = first.score(first.pick(req))[LE];
        tables.early = combine(ORDERS.relaxed, L);
        picks.early = tables.early.pick(req);
      }
      const plans = [];
      const seen = new Map();
      for (const o of OBJECTIVES) {
        if (picks[o] < 0) continue;
        const p = describe(o, tables[o].legs(picks[o]), prep, P, false);
        const key = legKey(p);
        if (seen.has(key)) { seen.get(key).also.push(o); continue; }
        p.also = [];
        seen.set(key, p);
        plans.push(p);
      }
      // fallback 1 (§3.5): for a film left out, the best plan that takes it in by giving up one film of the
      // main plan (and, when no single swap works, the best plan that has it at all)
      const main = plans[0];
      const mainMask = picks.relaxed;
      const T = tables.relaxed;
      const alts = new Map();
      const add = (mask) => { if (mask >= 0 && !alts.has(mask)) alts.set(mask, T.score(mask)); return mask >= 0; };
      prep.keys.forEach((f, fi) => {
        const bit = (1 << fi) >>> 0;
        if (mainMask & bit || !prep.byFilm[fi].length) return;
        let found = false;
        for (let gi = 0; gi < prep.k; gi++) {
          const g = (1 << gi) >>> 0;
          if (!(mainMask & g) || req & g) continue;
          if (add(T.pick(((mainMask & ~g) | bit | req) >>> 0))) found = true;
        }
        if (!found) add(T.pick((req | bit) >>> 0));
      });
      const drop = [...alts.entries()].sort((a, b) => cmp(a[1], b[1], ORDERS.relaxed)).slice(0, 3).map(([mask]) => {
        const p = describe("drop", T.legs(mask), prep, P, false);
        p.gained = p.covered.filter((f) => !main.covered.includes(f));
        p.dropped = main.covered.filter((f) => !p.covered.includes(f));
        return p;
      });
      return { lockConflict: false, plans, drop, maxFilms: main.stats.films };
    }

    function emptyResult(prep, extra) {
      return Object.assign({ plans: [], drop: [], maxFilms: 0, selected: prep.k,
        schedulable: prep.byFilm.filter((l) => l.length).length, approx: false, approxReason: null,
        lockConflict: false, needFallback: false, ms: 0 }, extra);
    }

    /** The main solve: {plans (1–3, distinct), drop (fallback-1 alternatives when not every film fits),
     *  maxFilms, selected, schedulable (films with a screening left), approx, approxReason ("size" | "timeout"),
     *  lockConflict (the locked screenings can't all be kept), needFallback (run planOverlap next), ms}. */
    function plan(showings, films, opts) {
      const t0 = Date.now();
      const P = params(opts);
      const prep = prepare(showings, films, P);
      if (!prep.k || !prep.n) return emptyResult(prep, { ms: Date.now() - t0 });
      const exact = prep.k <= P.exactMaxFilms && 2 ** prep.k * prep.n <= P.exactMaxWork;
      let r = null, approxReason = exact ? null : "size";
      if (exact) {
        try { r = solveStrict(prep, P, false, clockUntil(t0 + P.timeoutMs)); }
        catch (e) { if (e !== TIMEOUT) throw e; approxReason = "timeout"; }
      }
      if (!r) r = solveStrict(prep, P, true, () => {});
      const res = emptyResult(prep, r);
      res.approx = !!approxReason;
      res.approxReason = approxReason;
      res.needFallback = !r.lockConflict && P.maxOverlap > 0 && r.maxFilms < res.schedulable;
      res.ms = Date.now() - t0;
      return res;
    }

    /** Fallback 2 (§3.5): allow adjacent screenings to overlap by up to maxOverlap minutes. The plan, only when
     *  it fits more films than the strict solve (`strictFilms`); otherwise null. */
    function planOverlap(showings, films, opts, strictFilms) {
      const t0 = Date.now();
      const P = params(opts);
      if (!P.maxOverlap) return null;
      const prep = prepare(showings, films, P);
      if (!prep.k || !prep.n) return null;
      const run = (approx, tick) => {
        const finals = prep.blocks.map((b) => blockStates(b, P, true, approx ? P.beamWidth : 0, tick));
        const bests = finals.map((f) => bestBySet(f, ORDERS.relaxed));
        return approx ? combineBeam(bests, ORDERS.relaxed, P.beamWidth, tick) : combineExact(prep.k, bests, ORDERS.relaxed, tick);
      };
      let table = null, approx = !(prep.k <= P.exactMaxFilms && 2 ** prep.k * prep.n <= P.exactMaxWork);
      if (!approx) {
        try { table = run(false, clockUntil(t0 + P.timeoutMs)); } catch (e) { if (e !== TIMEOUT) throw e; approx = true; }
      }
      if (!table) table = run(true, () => {});
      const mask = table.pick(prep.lockedMask);
      if (mask < 0 || popcount(mask) <= (strictFilms || 0)) return null;
      const p = describe("overlap", table.legs(mask), prep, P, true);
      p.approx = approx;
      return p;
    }

    /** "Another screening" (§3.6) for screening `legId` of a plan made of `legIds`: exclude it and keep the
     *  plan's other screenings; when that leaves its film out, let the others move too. → {result (as plan()),
     *  opts (what to keep: `legId` added to `excluded`), adjusted (true when the others were let move)}. */
    function swap(showings, films, opts, legIds, legId) {
      const base = Object.assign({}, opts, { excluded: [...new Set([...((opts && opts.excluded) || []), legId])] });
      const film = (showings.find((s) => s.id === legId) || {}).filmKey;
      const keep = legIds.filter((id) => id !== legId);
      const first = plan(showings, films, Object.assign({}, base, { locked: [...new Set([...(base.locked || []), ...keep])] }));
      if (first.plans.length && first.plans[0].covered.includes(film)) return { result: first, opts: base, adjusted: false };
      return { result: plan(showings, films, base), opts: base, adjusted: true };
    }

    /** Both solves in one call (tests, and pages without Web Workers). */
    function solveAll(showings, films, opts) {
      const res = plan(showings, films, opts);
      res.overlap = res.needFallback ? planOverlap(showings, films, opts, res.maxFilms) : null;
      return res;
    }

    // ---------- share links (§4.3) ----------
    function encode(obj) {
      const bytes = new TextEncoder().encode(JSON.stringify(obj));
      let bin = "";
      for (const b of bytes) bin += String.fromCharCode(b);
      return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    }
    function decode(str) {
      try {
        let b64 = String(str).replace(/-/g, "+").replace(/_/g, "/");
        while (b64.length % 4) b64 += "=";
        const bin = atob(b64);
        return JSON.parse(new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0))));
      } catch (_) {
        return null;
      }
    }

    /** {from, to, venues|null, film, subs, specials, dayWindow, maxPerDay, forbidTight, maxOverlap, films (keys),
     *  locked, excluded} → the compact object a share link carries (film keys as short ids). */
    function toShare(st) {
      const o = { v: 1, f: st.from, t: st.to, k: (st.films || []).map(filmId) };
      if (st.venues) o.vs = [...st.venues];
      if (st.film) o.film = 1;
      if (st.subs) o.sub = 1;
      if (st.specials) o.sp = 1;
      if (st.dayWindow) o.w = [st.dayWindow.earliest, st.dayWindow.latest];
      if (st.maxPerDay) o.mpd = st.maxPerDay;
      if (st.forbidTight) o.ft = 1;
      if (st.maxOverlap !== DEFAULTS.maxOverlap) o.mo = st.maxOverlap;
      if (st.locked && st.locked.length) o.l = [...st.locked];
      if (st.excluded && st.excluded.length) o.x = [...st.excluded];
      return o;
    }
    /** The inverse; `filmKeyById` maps short ids back to film keys (ids no longer in the data are dropped). */
    function fromShare(o, filmKeyById) {
      if (!o || o.v !== 1 || !/^\d{4}-\d{2}-\d{2}$/.test(o.f || "") || !/^\d{4}-\d{2}-\d{2}$/.test(o.t || "")) return null;
      const arr = (x) => (Array.isArray(x) ? x.filter((y) => typeof y === "string") : []);
      return {
        from: o.f, to: o.t, venues: Array.isArray(o.vs) ? arr(o.vs) : null,
        film: !!o.film, subs: !!o.sub, specials: !!o.sp,
        dayWindow: Array.isArray(o.w) && hhmm(o.w[0]) != null && hhmm(o.w[1]) != null ? { earliest: o.w[0], latest: o.w[1] } : null,
        maxPerDay: o.mpd > 0 ? Math.floor(o.mpd) : null, forbidTight: !!o.ft,
        maxOverlap: o.mo == null ? DEFAULTS.maxOverlap : Math.max(0, Math.min(30, +o.mo || 0)),
        films: arr(o.k).map((id) => filmKeyById.get(id)).filter(Boolean),
        locked: arr(o.l), excluded: arr(o.x),
      };
    }

    return {
      DEFAULTS, MAX_FILMS, OBJECTIVES, fold, plain, titleKey, filmKeys, filmId, groupFilms, candidates, minutesInDay,
      needsNoEnglish, params, link, comfort, plan, planOverlap, swap, solveAll, encode, decode, toShare, fromShare,
    };
  }

  /** The Web Worker: one message {id, showings, films, opts, swap?: {legs, leg}} → {id, phase: "main", result,
   *  swap: {opts, adjusted} | null}, then {id, phase: "overlap", result: plan | null}. */
  function workerMain(P) {
    self.onmessage = (e) => {
      const { id, showings, films, swap } = e.data;
      let opts = e.data.opts;
      try {
        let main, extra = null;
        if (swap) {
          const r = P.swap(showings, films, opts, swap.legs, swap.leg);
          main = r.result;
          opts = r.opts;
          extra = { opts: r.opts, adjusted: r.adjusted };
        } else main = P.plan(showings, films, opts);
        self.postMessage({ id, phase: "main", result: main, swap: extra });
        self.postMessage({ id, phase: "overlap", result: main.needFallback ? P.planOverlap(showings, films, opts, main.maxFilms) : null });
      } catch (err) {
        self.postMessage({ id, phase: "error", error: String((err && err.stack) || err) });
      }
    };
  }

  const api = factory();
  /** Source text for a Worker built from a Blob (so no second file is fetched, and file:// pages work). */
  api.workerSource = () => `"use strict";\n(${workerMain.toString()})((${factory.toString()})());\n`;
  root.CinemaPlan = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
