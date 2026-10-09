"""The planner's solver (site/plan.js, run under Node): one screening per film, no overlaps, comfortable changes,
three objectives and the two fallbacks of PLANNER.md §3.5. Fixtures: tests/fixtures/plan/*.json."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PLAN_JS = ROOT / "site" / "plan.js"
FIXTURES = ROOT / "tests" / "fixtures" / "plan"

# Loads a fixture, picks its films (by title; all by default), solves, and prints a summary keyed by title.
RUNNER = r"""
const P = require(process.argv[1]);
const fx = JSON.parse(require("fs").readFileSync(process.argv[2], "utf8"));
const args = JSON.parse(process.argv[3]);
for (const [id, patch] of Object.entries(args.patch || {})) Object.assign(fx.screenings.find((s) => s.id === id), patch);
const keys = P.filmKeys(fx.screenings);
const cands = P.candidates(fx, keys, Object.assign({}, fx.scope, args.scope || {}));
const titleOf = new Map(cands.map((s) => [s.filmKey, s.source.title]));
const films = P.groupFilms(cands);
const titles = args.films || fx.films;
const chosen = titles ? titles.map((t) => films.find((f) => f.title === t).key) : films.slice(0, args.limit || 99).map((f) => f.key);
const opts = Object.assign({}, fx.opts || {}, args.opts || {});
const brief = (p) => p && {
  objective: p.objective, also: p.also, legs: p.legs.map((s) => s.id), titles: p.legs.map((s) => titleOf.get(s.filmKey)),
  days: p.legs.map((s) => s.day), films: p.legs.map((s) => s.filmKey),
  stats: p.stats, gaps: p.gaps, unknownRuntime: p.unknownRuntime,
  gained: (p.gained || []).map((f) => titleOf.get(f)), dropped: (p.dropped || []).map((f) => titleOf.get(f)),
  uncovered: p.uncovered.map((u) => Object.assign({}, u, { title: titleOf.get(u.filmKey), with: (u.with || []).map((f) => titleOf.get(f)) })),
  check: (() => {          // legality, recomputed independently of the solver
    const L = p.legs, seen = new Set(), bad = [];
    L.forEach((s, i) => {
      if (seen.has(s.filmKey)) bad.push("twice " + s.id);
      seen.add(s.filmKey);
      if (i && L[i - 1].start > s.start) bad.push("order " + s.id);
      const a = L[i - 1];
      if (!i) return;
      const gap = (s.start - a.end) / 60e3;
      const allowed = p.objective === "overlap" && a.day === s.day ? -(opts.maxOverlap ?? 15) : 0;
      if (gap < allowed) bad.push(`overlap ${a.id}->${s.id}`);
      if (a.day === s.day && a.region !== s.region && gap < 180) bad.push(`regions ${a.id}->${s.id}`);
    });
    return bad;
  })(),
};
let out;
if (args.swap) {
  const first = P.plan(cands, chosen, opts);
  const r = P.swap(cands, chosen, opts, first.plans[0].legs.map((s) => s.id), args.swap);
  out = { before: brief(first.plans[0]), after: brief(r.result.plans[0]), adjusted: r.adjusted, excluded: r.opts.excluded };
} else {
  const t0 = Date.now();
  const r = P.solveAll(cands, chosen, opts);
  out = { ms: Date.now() - t0, approx: r.approx, approxReason: r.approxReason, maxFilms: r.maxFilms, selected: r.selected,
    schedulable: r.schedulable, lockConflict: r.lockConflict, needFallback: r.needFallback,
    plans: r.plans.map(brief), drop: r.drop.map(brief), overlap: brief(r.overlap) };
}
console.log(JSON.stringify(out));
"""


def solve(fixture, **args):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    path = fixture if isinstance(fixture, Path) else FIXTURES / f"{fixture}.json"
    out = subprocess.run(["node", "-e", RUNNER, str(PLAN_JS), str(path), json.dumps(args)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def legal(r):
    for p in r.get("plans", []) + r.get("drop", []) + [r.get("overlap")]:
        if p:
            assert p["check"] == [], p["check"]
            assert p["stats"]["films"] == len(p["legs"]) == len(set(p["films"]))
    return r


# 1
def test_overlapping_pair_keeps_one_and_says_why():
    r = legal(solve("conflict"))
    assert r["maxFilms"] == 1 and len(r["plans"]) == 1
    p = r["plans"][0]
    assert len(p["uncovered"]) == 1
    u = p["uncovered"][0]
    assert u["reason"] == "conflict" and u["count"] == 1 and u["only"] and u["with"] == [p["titles"][0]]
    assert r["overlap"] is None                                     # 60 minutes of overlap is too much to miss


# 2
def test_all_three_films_with_the_widest_short_gaps():
    r = legal(solve("widest"))
    p = r["plans"][0]
    assert r["maxFilms"] == 3 and p["legs"] == ["a1", "b2", "c2"]
    assert [g["minutes"] for g in p["gaps"]] == [40, 40] and p["stats"]["minGap"] == 40
    assert [g["kind"] for g in p["gaps"]] == ["same-region", "same-region"]


# 3
def test_tight_changes_are_avoided_and_can_be_forbidden():
    p = legal(solve("tight"))["plans"][0]
    assert p["legs"] == ["a1", "b2"] and p["stats"]["tightCount"] == 0 and p["stats"]["minGap"] == 40
    p = legal(solve("tight", opts={"excluded": ["b2"]}))["plans"][0]
    assert p["legs"] == ["a1", "b1"] and p["stats"]["tightCount"] == 1 and p["gaps"][0]["tight"]
    r = legal(solve("tight", opts={"excluded": ["b2"], "forbidTight": True}))
    assert r["maxFilms"] == 1 and r["plans"][0]["uncovered"][0]["reason"] == "conflict"


# 4
def test_a_change_across_midnight_into_the_next_day_is_not_a_gap():
    p = legal(solve("overnight"))["plans"][0]
    assert p["legs"] == ["a1", "b1"]
    assert p["gaps"] == [] and p["stats"]["tightCount"] == 0 and p["stats"]["minGap"] is None
    assert p["stats"]["days"] == 2 and p["stats"]["comfort"] == 0


# 5
def test_another_region_on_the_same_day_needs_three_hours():
    p = legal(solve("regions"))["plans"][0]
    assert p["legs"] == ["a1", "b2"] and p["gaps"][0]["kind"] == "cross-region" and not p["gaps"][0]["tight"]
    r = legal(solve("regions", opts={"excluded": ["b2"]}))
    assert r["maxFilms"] == 1
    u = r["plans"][0]["uncovered"][0]
    assert u["reason"] == "conflict"


# 6
def test_unknown_runtime_counts_as_two_hours_and_is_flagged():
    p = legal(solve("unknown_runtime"))["plans"][0]
    assert p["legs"] == ["a1", "b2"] and p["unknownRuntime"] == ["a1"]
    assert p["gaps"][0]["minutes"] == 15 and not p["gaps"][0]["tight"]          # 19:00 + 120 → 21:00, then 21:15
    r = legal(solve("unknown_runtime", opts={"excluded": ["b2"]}))
    assert r["maxFilms"] == 1


# 7
def test_lock_exclude_and_swap():
    assert legal(solve("lock"))["plans"][0]["legs"] == ["a1", "b2"]
    assert legal(solve("lock", opts={"locked": ["a2"]}))["plans"][0]["legs"] == ["b1", "a2"]
    assert legal(solve("lock", opts={"excluded": ["a1"]}))["plans"][0]["legs"] == ["b1", "a2"]
    r = solve("lock", swap="b2")
    assert r["before"]["legs"] == ["a1", "b2"] and r["after"]["legs"] == ["a1", "b1"]
    assert r["adjusted"] is False and r["excluded"] == ["b2"]
    # Beta's only other screening clashes with the kept Alpha: the others are let move
    r = solve("lock", swap="b2", opts={"excluded": ["a2"]}, patch={"b1": {"start": "2026-10-10T13:30:00-04:00", "end": "2026-10-10T15:00:00-04:00"}})
    assert r["after"]["legs"] == ["a1"] or r["adjusted"] is True
    # two locked screenings that overlap can't both be kept
    r = solve("conflict", opts={"locked": ["a1", "b1"]})
    assert r["lockConflict"] is True and r["plans"] == []


# 8
def test_relaxed_and_compact_objectives_differ():
    r = legal(solve("objectives"))
    by = {p["objective"]: p for p in r["plans"]}
    assert by["relaxed"]["legs"] == ["a1", "b2"] and by["relaxed"]["stats"]["days"] == 2
    assert by["compact"]["legs"] == ["a1", "b1"] and by["compact"]["stats"]["days"] == 1
    assert len({tuple(p["legs"]) for p in r["plans"]}) == len(r["plans"])         # never the same plan twice


def test_early_objective_finishes_earliest():
    r = legal(solve("lock"))
    early = next(p for p in r["plans"] if "early" in [p["objective"], *p["also"]])
    assert early["stats"]["lastEndMin"] == min(p["stats"]["lastEndMin"] for p in r["plans"])


# 8a
def test_drop_alternatives_each_give_up_a_different_film():
    r = legal(solve("drop"))
    assert r["maxFilms"] == 2 and r["schedulable"] == 3 and r["needFallback"] is True
    main = r["plans"][0]
    left_out = main["uncovered"][0]["title"]
    assert len(r["drop"]) == 2
    assert {tuple(d["dropped"]) for d in r["drop"]} == {(t,) for t in main["titles"]}
    assert all(d["gained"] == [left_out] and d["stats"]["films"] == 2 for d in r["drop"])
    assert r["overlap"] is None


# 8b
def test_missing_a_few_minutes_fallback():
    r = legal(solve("overlap"))
    assert r["maxFilms"] == 1
    ov = r["overlap"]
    assert ov["legs"] == ["a1", "b1"] and ov["stats"]["overlapMinutes"] == 10 and ov["stats"]["overlapCount"] == 1
    assert ov["gaps"][0]["overlap"] == 10
    assert solve("overlap", opts={"maxOverlap": 5})["overlap"] is None
    assert solve("overlap", opts={"maxOverlap": 0})["overlap"] is None
    assert solve("overlap_unknown")["overlap"] is None


# 8c
def test_a_film_never_loses_more_than_the_cap_at_both_ends():
    r = legal(solve("overlap_chain"))
    assert r["maxFilms"] == 2
    assert r["overlap"] is None or len(r["overlap"]["legs"]) < 3
    ov = legal(solve("overlap_chain", opts={"maxOverlap": 20}))["overlap"]
    assert ov["legs"] == ["a1", "b1", "c1"] and ov["stats"]["overlapMinutes"] == 20


# 8d
def test_no_fallback_when_everything_fits():
    r = legal(solve("fits"))
    assert r["maxFilms"] == 2 and r["needFallback"] is False and r["overlap"] is None and r["drop"] == []


# 9
def _synthetic(tmp_path, films, per_film, days=14):
    """`films` films with `per_film` screenings each, spread over `days` days at four cinemas in two regions."""
    import random
    rnd = random.Random(7)
    venues = [{"id": v, "name": v, "region": r, "timezone": "America/New_York", "status": "ok"}
              for v, r in (("v1", "NYC"), ("v2", "NYC"), ("v3", "NYC"), ("v4", "PHL"))]
    screenings = []
    for f in range(films):
        runtime = rnd.choice([80, 95, 105, 120, 140])
        for i in range(per_film):
            day = f"2026-10-{10 + rnd.randrange(days):02d}"
            h, m = rnd.randrange(11, 22), rnd.choice([0, 15, 30, 45])
            start = f"{day}T{h:02d}:{m:02d}:00-04:00"
            screenings.append({"id": f"f{f}s{i}", "venue_id": rnd.choice(venues)["id"], "title": f"Film {f}",
                               "start": start, "end": None, "day": day, "runtime_min": runtime, "year": 2000 + f})
    path = tmp_path / f"synthetic-{films}.json"
    path.write_text(json.dumps({"venues": venues, "screenings": screenings,
                                "scope": {"from": "2026-10-10", "to": f"2026-10-{9 + days:02d}"}}))
    return path


def test_twelve_films_solve_exactly_in_time(tmp_path):
    r = legal(solve(_synthetic(tmp_path, 12, 30)))
    assert r["selected"] == 12 and r["approx"] is False
    assert r["maxFilms"] == 12
    assert r["ms"] < 1500, r["ms"]


def test_twenty_films_fall_back_to_the_beam(tmp_path):
    r = legal(solve(_synthetic(tmp_path, 20, 30)))
    assert r["selected"] == 20 and r["approx"] is True and r["approxReason"] == "size"
    assert r["maxFilms"] >= 18 and r["plans"]


# 10
def test_real_sample_plans_are_legal_and_their_stats_add_up():
    r = legal(solve("real_sample", limit=10))
    assert r["plans"]
    for p in r["plans"] + r["drop"] + ([r["overlap"]] if r["overlap"] else []):
        st, gaps = p["stats"], p["gaps"]
        assert st["days"] == len(set(p["days"]))
        assert st["tightCount"] == sum(g["tight"] for g in gaps)
        assert st["overlapMinutes"] == sum(g["overlap"] for g in gaps)
        plain = [g["minutes"] for g in gaps if not g["overlap"]]
        assert st["minGap"] == (min(plain) if plain else None)
        assert st["films"] + len(p["uncovered"]) == st["of"] == 10


def test_film_identity_merges_spellings_and_imdb_ids():
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    script = """
      const P = require(process.argv[1]);
      const S = (id, title, extra) => Object.assign({ id, title, year: 1997, director: null, imdb_id: null }, extra);
      const keys = P.filmKeys([
        S("a", "Happy Together"), S("b", "HAPPY TOGETHER!"), S("c", "Happy Together", { imdb_id: "tt0118845" }),
        S("d", "Happy Together", { year: 2026 }), S("e", "Le Samouraï", { year: null, director: "Melville" }),
        S("f", "LE SAMOURAI", { year: null, director: "Jean-Pierre Melville" }),
      ]);
      console.log(JSON.stringify(Object.fromEntries(keys)));
    """
    out = subprocess.run(["node", "-e", script, str(PLAN_JS)], capture_output=True, text=True, check=True)
    k = json.loads(out.stdout)
    assert k["a"] == k["b"] == k["c"] == "i:tt0118845"           # one IMDb id for that title and year: joined
    assert k["d"] != k["a"]                                        # another year, another film
    assert k["e"].startswith("t:le samourai||") and k["e"] != k["f"]   # no year: the director decides


def test_share_payload_round_trip():
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    script = """
      const P = require(process.argv[1]);
      const st = { from: "2026-10-10", to: "2026-10-16", venues: ["filmforum", "bam"], film: true, subs: false, specials: true,
        dayWindow: { earliest: "12:00", latest: "23:30" }, maxPerDay: 3, forbidTight: true, maxOverlap: 20,
        films: ["i:tt0118845", "t:naza|2026"], locked: ["abc"], excluded: ["def"] };
      const s = P.encode(P.toShare(st));
      const back = P.fromShare(P.decode(s), new Map(st.films.map((k) => [P.filmId(k), k])));
      console.log(JSON.stringify({ s, back, bad: P.decode("%%%"), stale: P.fromShare(P.decode(s), new Map()).films }));
    """
    out = subprocess.run(["node", "-e", script, str(PLAN_JS)], capture_output=True, text=True, check=True)
    r = json.loads(out.stdout)
    assert all(c.isalnum() or c in "-_" for c in r["s"])                       # URL-safe
    b = r["back"]
    assert b["from"] == "2026-10-10" and b["venues"] == ["filmforum", "bam"] and b["film"] and b["specials"] and not b["subs"]
    assert b["dayWindow"] == {"earliest": "12:00", "latest": "23:30"} and b["maxPerDay"] == 3 and b["forbidTight"]
    assert b["maxOverlap"] == 20 and b["films"] == ["i:tt0118845", "t:naza|2026"]
    assert b["locked"] == ["abc"] and b["excluded"] == ["def"]
    assert r["bad"] is None and r["stale"] == []


def test_candidates_follow_scope_filters_and_time_window():
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    script = """
      const P = require(process.argv[1]);
      const V = [{ id: "a", region: "NYC", timezone: "America/New_York", status: "ok" },
                 { id: "z", region: "NYC", timezone: "America/New_York", status: "disabled" }];
      const S = (id, venue_id, start, extra) => Object.assign({ id, venue_id, title: "T" + id, start, end: null,
        day: start.slice(0, 10), runtime_min: 100, format: "DCP", language: "English", run: false }, extra);
      const D = { venues: V, screenings: [
        S("1", "a", "2026-10-10T10:00:00-04:00"), S("2", "a", "2026-10-10T19:00:00-04:00", { format: "35mm" }),
        S("3", "a", "2026-10-10T19:00:00-04:00", { id: "3", title: "T2", format: "35mm" }),   // twin of 2 on another screen
        S("4", "z", "2026-10-10T19:00:00-04:00"), S("5", "a", "2026-10-11T22:30:00-04:00", { language: "French" }),
        S("6", "a", "2026-10-12T12:00:00-04:00", { run: true }), S("7", "a", "2026-10-13T12:00:00-04:00") ] };
      const ids = (sc) => P.candidates(D, P.filmKeys(D.screenings), sc).map((s) => s.id);
      console.log(JSON.stringify({
        all: ids({ from: "2026-10-10", to: "2026-10-12" }),
        film: ids({ from: "2026-10-10", to: "2026-10-12", film: true }),
        subs: ids({ from: "2026-10-10", to: "2026-10-12", subs: true }),
        specials: ids({ from: "2026-10-10", to: "2026-10-12", specials: true }),
        now: ids({ from: "2026-10-10", to: "2026-10-12", now: Date.parse("2026-10-10T12:00:00-04:00") }),
        window: ids({ from: "2026-10-10", to: "2026-10-13", dayWindow: { earliest: "11:00", latest: "23:59" } }),
        venues: ids({ from: "2026-10-10", to: "2026-10-13", venues: [] }),
        unknown: P.candidates({ venues: V, screenings: [S("8", "a", "2026-10-10T19:00:00-04:00", { runtime_min: null })] }, null, {})
          .map((s) => [s.endKnown, (s.end - s.start) / 60e3, s.startMin, s.endMin]),
      }));
    """
    out = subprocess.run(["node", "-e", script, str(PLAN_JS)], capture_output=True, text=True, check=True)
    r = json.loads(out.stdout)
    assert r["all"] == ["1", "2", "5", "6"]                 # disabled cinema and day 13 left out; the twin counted once
    assert r["film"] == ["2"] and r["subs"] == ["5"] and r["specials"] == ["1", "2", "5"]
    assert r["now"] == ["2", "5", "6"]
    assert r["window"] == ["2", "6", "7"]                   # 10:00 starts too early; 22:30 + 100 min ends past 23:59
    assert r["venues"] == []
    assert r["unknown"] == [[False, 120, 1140, 1260]]


def test_both_pages_load_the_planner_and_publishing_ships_it():
    site = ROOT / "site"
    main = (site / "index.html").read_text()
    phone = (site / "m" / "venues" / "index.html").read_text()
    for name in ("plan.js", "planner.js", "planner.css"):
        assert f'"{name}"' in main and f'"../../{name}"' in phone
        assert name in (ROOT / "scripts" / "stamp_assets.py").read_text()
    assert main.index('"app.js"') < main.index('"plan.js"') < main.index('"planner.js"')
    assert phone.index('"venues.js"') < phone.index('"../../planner.js"')          # after the phone shell has drawn
    assert 'location.search + location.hash' in main                             # ?plan= survives the phone redirect
    ship = "cp site/plan.js site/planner.js site/planner.css"
    assert ship in (ROOT / "scripts" / "publish.sh").read_text()
    assert ship in (ROOT / ".github" / "workflows" / "refresh.yml").read_text()
