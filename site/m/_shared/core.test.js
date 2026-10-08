/* Offline tests for site/m/_shared/core.js — run with `node site/m/_shared/core.test.js` (no dependencies;
 * also run by tests/test_mobile_core.py). The expectations mirror site/app.js where the two must agree:
 * URL parameters, stored cinema / region choice, filter meaning, grouping. */
"use strict";
const assert = require("assert");
const C = require("./core.js");

const NY = "America/New_York";
const V = (id, region, extra = {}) => ({ id, name: id.toUpperCase(), short: id, color: "#888", region, timezone: NY, status: "ok", source: "primary", ...extra });
const S = (id, venue_id, start, extra = {}) => ({
  id, venue_id, title: "Film " + id, start, end: null, day: start.slice(0, 10), director: null, year: null, runtime_min: 100,
  format: "DCP", series: null, screen: null, note: null, detail_url: null, ticket_url: null, source: "primary", language: "English", run: false, ...extra,
});
const DATA = {
  generated_at: "2026-10-08T17:00:00Z",
  venues: [V("metrograph", "NYC"), V("filmforum", "NYC"), V("pfs", "PHL"), V("old", "PHL", { status: "disabled" })],
  screenings: [
    S("a", "metrograph", "2026-10-10T19:00:00-04:00", { title: "Happy Together", format: "35mm", language: "Cantonese", director: "Wong Kar-wai", year: 1997 }),
    S("b", "filmforum", "2026-10-10T13:00:00-04:00", { title: "Happy Together!", director: "Wong Kar Wai", year: 1997 }),
    S("c", "pfs", "2026-10-10T21:00:00-04:00", { title: "HAPPY TOGETHER", year: 2026, director: "Someone Else", run: true }),
    S("d", "metrograph", "2026-10-10T23:30:00-04:00", { title: "Midnight Movie", note: "Open captions" }),
    S("e", "filmforum", "2026-10-11T00:30:00-04:00", { title: "After Hours", day: "2026-10-10" }),
    S("f", "metrograph", "2026-10-10T19:00:00-04:00", { title: "Happy Together", screen: "Screen 2", format: "35mm" }),
    S("g", "filmforum", "2026-10-12T15:00:00-04:00", { title: "Le Samouraï", language: "French", series: "Melville" }),
  ],
  days: {
    "2026-10-10": ["a", "b", "c", "d", "e", "f"],
    "2026-10-12": ["g"],
  },
};
const m = C.model(DATA);
const TODAY = "2026-10-08";
const memStore = (init = {}) => {
  const d = { ...init };
  return { getItem: (k) => (k in d ? d[k] : null), setItem: (k, v) => { d[k] = String(v); }, dump: () => d };
};

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

// ---------- time ----------
test("times are shown in the cinema's zone, minutes run past midnight", () => {
  assert.strictEqual(C.timeLabel("2026-10-10T19:00:00-04:00", NY), "7:00pm");
  assert.strictEqual(C.timeLabel("2026-10-10T19:00:00-04:00", "America/Los_Angeles"), "4:00pm");
  assert.deepStrictEqual(C.timeParts("2026-10-10T09:05:00-04:00", NY), { hm: "9:05", ap: "am" });
  assert.strictEqual(C.minutesInDay("2026-10-10T19:30:00-04:00", "2026-10-10", NY), 19 * 60 + 30);
  assert.strictEqual(C.minutesInDay("2026-10-11T00:30:00-04:00", "2026-10-10", NY), 24 * 60 + 30);
  assert.strictEqual(C.hourLabel(0), "12 AM");
  assert.strictEqual(C.hourLabel(13 * 60 + 5), "1 PM");
  assert.strictEqual(C.hourLabel(24 * 60 + 30), "12 AM");
});

test("day keys, shifting, titles", () => {
  assert.strictEqual(C.shiftDay("2026-10-31", 1), "2026-11-01");
  assert.strictEqual(C.shiftDay("2026-03-01", -1), "2026-02-28");
  assert.strictEqual(C.daysBetween("2026-10-08", "2026-10-15"), 7);
  assert.ok(C.validDay("2026-10-08") && !C.validDay("2026-13-40x") && !C.validDay(""));
  assert.strictEqual(C.dayTitle("2026-10-08", "zh"), "10月8日 周四");
  assert.strictEqual(C.dayTitle("2026-10-08", "en"), "Thu, Oct 8");
  assert.strictEqual(C.weekday("2026-10-09", "zh"), "周五");
  const t = C.translator("en");
  assert.strictEqual(C.relDay("2026-10-08", TODAY, t), "Today");
  assert.strictEqual(C.relDay("2026-10-09", TODAY, t), "Tomorrow");
  assert.strictEqual(C.relDay("2026-10-10", TODAY, t), "");
});

test("language: hash, then saved choice, then the browser", () => {
  const st = memStore({ "cinema.lang": "en" });
  assert.strictEqual(C.initialLang("#/?lang=zh", st, "en-US"), "zh");
  assert.strictEqual(st.dump()["cinema.lang"], "zh");
  assert.strictEqual(C.initialLang("#/", memStore({ "cinema.lang": "en" }), "zh-CN"), "en");
  assert.strictEqual(C.initialLang("#/", memStore(), "zh-TW"), "zh");
  assert.strictEqual(C.initialLang("#/", null, "fr"), "en");
});

// ---------- URL hash: the main page's parameters ----------
test("a main-page link opens the same day, cinemas and filters", () => {
  const st = C.parseHash("#/2026-10-10?v=metrograph,filmforum&film=1", m, TODAY, memStore());
  assert.strictEqual(st.day, "2026-10-10");
  assert.deepStrictEqual([...st.venues], ["metrograph", "filmforum"]);
  assert.deepStrictEqual([...st.regions], ["NYC", "PHL"]);
  assert.ok(st.film && !st.subs && !st.upcoming && !st.specials);
  assert.strictEqual(C.buildHash(st, m, TODAY), "#/2026-10-10?v=metrograph,filmforum&film=1");
});

test("hash round trip keeps every parameter, including the main page's own", () => {
  const h = "#/2026-10-12?view=list&v=pfs&r=PHL&film=1&sub=1&up=1&sp=1&q=wong+kar&ws=today&hl=Happy+Together";
  const st = C.parseHash(h, m, TODAY, memStore());
  assert.strictEqual(st.q, "wong kar");
  assert.strictEqual(st.hl, "Happy Together");
  assert.strictEqual(st.view, "list");
  assert.strictEqual(C.buildHash(st, m, TODAY), h);
});

test("a past or broken date lands on today; today stays date-less", () => {
  assert.strictEqual(C.parseHash("#/2026-10-01", m, TODAY, null).day, TODAY);
  assert.strictEqual(C.parseHash("#/nonsense?film=1", m, TODAY, null).day, TODAY);
  assert.strictEqual(C.buildHash(C.parseHash("", m, TODAY, null), m, TODAY), "#/");
});

test("r= means no region; unknown names mean all; unknown cinemas are dropped", () => {
  assert.strictEqual(C.parseHash("#/?r=", m, TODAY, null).regions.size, 0);
  assert.strictEqual(C.parseHash("#/?r=LA", m, TODAY, null).regions.size, 2);
  assert.deepStrictEqual([...C.parseHash("#/?v=nope,pfs", m, TODAY, null).venues], ["pfs"]);
  assert.strictEqual(C.parseHash("#/?v=nope", m, TODAY, null).venues.size, 3);    // all active cinemas
});

// ---------- storage: the main page's keys ----------
test("cinema choice is stored as {on, known}; cinemas added later start selected", () => {
  const st = memStore();
  const s1 = C.parseHash("#/?v=metrograph", m, TODAY, st);
  C.saveVenues(st, s1, m);
  assert.deepStrictEqual(JSON.parse(st.dump()["cinema.venues"]), { on: ["metrograph"], known: ["metrograph", "filmforum", "pfs"] });
  assert.deepStrictEqual([...C.parseHash("#/", m, TODAY, st).venues], ["metrograph"]);
  const older = memStore({ "cinema.venues": JSON.stringify({ on: ["metrograph"], known: ["metrograph", "filmforum"] }) });
  assert.deepStrictEqual([...C.loadVenues(older, m)], ["metrograph", "pfs"]);
  assert.strictEqual(C.loadVenues(memStore({ "cinema.venues": "{bad json" }), m), null);
});

test("regions: [] stored on purpose stays empty", () => {
  const st = memStore({ "cinema.regions": "[]" });
  assert.strictEqual(C.loadRegions(st, m).size, 0);
  C.saveRegions(st, { regions: new Set(["PHL"]) });
  assert.deepStrictEqual([...C.loadRegions(st, m)], ["PHL"]);
});

// ---------- filters ----------
test("filters mean what they mean on the main page", () => {
  const base = C.parseHash("#/2026-10-10", m, TODAY, null);
  const now = new Date("2026-10-10T20:00:00-04:00");
  const ids = (patch) => C.visible(m, { ...base, ...patch }, "2026-10-10", now, "2026-10-10").map((s) => s.id);
  assert.deepStrictEqual(ids({}), ["b", "a", "f", "c", "d", "e"]);                       // by start, then title
  assert.deepStrictEqual(ids({ film: true }), ["a", "f"]);
  assert.deepStrictEqual(ids({ subs: true }), ["a", "d"]);                                   // non-English, or open captions
  assert.deepStrictEqual(ids({ upcoming: true }), ["c", "d", "e"]);                         // started ones hidden today only
  assert.deepStrictEqual(ids({ specials: true }), ["b", "a", "f", "d", "e"]);              // wide releases (run) hidden
  assert.deepStrictEqual(ids({ q: "WONG" }), ["b", "a"]);                                  // director, case-folded
  assert.deepStrictEqual(ids({ venues: new Set(["pfs", "metrograph"]), regions: new Set(["PHL"]) }), ["c"]);
  const later = C.visible(m, { ...base, upcoming: true }, "2026-10-10", now, "2026-10-09").length;
  assert.strictEqual(later, 6);                                                              // not today: nothing has started
  assert.strictEqual(C.needsNoEnglish({ language: null }), null);
  assert.strictEqual(C.needsNoEnglish({ language: "English, French" }), false);
  assert.strictEqual(C.needsNoEnglish({ language: "English", note: "Subtitled screening" }), true);
});

test("search folds accents", () => {
  const st = { ...C.parseHash("#/", m, TODAY, null), q: "samourai" };
  assert.deepStrictEqual(C.visible(m, st, "2026-10-12", new Date("2026-10-08T12:00:00-04:00"), TODAY).map((s) => s.id), ["g"]);
});

test("day counts and the nearest day with screenings", () => {
  const st = C.parseHash("#/", m, TODAY, null);
  const now = new Date("2026-10-08T12:00:00-04:00");
  assert.deepStrictEqual(C.dayCounts(m, st, ["2026-10-10", "2026-10-11", "2026-10-12"], now, TODAY),
    { "2026-10-10": 6, "2026-10-11": 0, "2026-10-12": 1 });
  assert.strictEqual(C.nearestDay(m, st, "2026-10-10", 1, now, TODAY), "2026-10-12");
  assert.strictEqual(C.nearestDay(m, st, "2026-10-12", -1, now, TODAY), "2026-10-10");
  assert.strictEqual(C.nearestDay(m, { ...st, film: true }, "2026-10-10", 1, now, TODAY), null);
});

// ---------- grouping ----------
test("groupFilms and groupByVenue behave as on the main page", () => {
  const list = m.forDay("2026-10-10");
  const films = C.groupFilms(list.filter((s) => s.venue_id === "metrograph"));
  assert.deepStrictEqual(films.map((f) => [f.title, f.showings.length]), [["Happy Together", 2], ["Midnight Movie", 1]]);
  assert.deepStrictEqual(C.groupByVenue(list).map(([v]) => v), ["filmforum", "metrograph", "pfs"]);
});

test("twins: one film starting together on two screens of a cinema", () => {
  const a = m.byId.a;
  assert.deepStrictEqual(m.twinsOf(a).map((s) => s.id), ["a", "f"]);
  assert.deepStrictEqual(C.groupTwins(m.forDay("2026-10-10")).map((g) => g.length), [1, 2, 1, 1, 1]);
});

test("films across cinemas: same title merges, a different year or director stays apart", () => {
  const groups = C.filmClusters(m.forDay("2026-10-10"));
  const happy = groups.filter((g) => C.normTitle(g.title) === "happy together");
  assert.strictEqual(happy.length, 2);
  assert.deepStrictEqual(happy[0].showings.map((s) => s.id), ["b", "a", "f"]);           // punctuation, case, "Wong Kar Wai"
  assert.deepStrictEqual(happy[1].showings.map((s) => s.id), ["c"]);                     // 2026, another director
  assert.strictEqual(happy[0].director, "Wong Kar Wai");
  assert.strictEqual(C.normTitle("Pierrot le Fou & Me"), "pierrot le fou and me");
});

test("lane packing and spans", () => {
  const items = [{ from: 600, to: 700 }, { from: 650, to: 760 }, { from: 705, to: 800 }];
  assert.strictEqual(C.packLanes(items), 2);
  assert.deepStrictEqual(items.map((i) => i.lane), [0, 1, 0]);
  assert.deepStrictEqual(C.span(m.byId.e, "2026-10-10", NY), { from: 1470, to: 1570, known: true });
  assert.deepStrictEqual(C.span({ ...m.byId.e, runtime_min: null }, "2026-10-10", NY), { from: 1470, to: 1570, known: false });
});

test("row facts: runtime, film gauge, a non-English language", () => {
  assert.deepStrictEqual(C.rowFacts(m.byId.a), ["100m", "35mm", "Cantonese"]);
  assert.deepStrictEqual(C.rowFacts(m.byId.b), ["100m"]);
});

test("the model skips disabled cinemas and sorts each day", () => {
  assert.deepStrictEqual(m.active.map((v) => v.id), ["metrograph", "filmforum", "pfs"]);
  assert.deepStrictEqual(m.regions, ["NYC", "PHL"]);
  assert.deepStrictEqual(m.days, ["2026-10-10", "2026-10-12"]);
  assert.strictEqual(m.forDay("2026-10-11").length, 0);
});

test("both languages define the same keys", () => {
  assert.deepStrictEqual(Object.keys(C.I18N.zh).sort(), Object.keys(C.I18N.en).sort());
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log(`ok   ${name}`); } catch (e) { failed++; console.log(`FAIL ${name}\n     ${e.message.split("\n").join("\n     ")}`); }
}
console.log(`${tests.length - failed}/${tests.length} passed`);
process.exit(failed ? 1 : 0);
