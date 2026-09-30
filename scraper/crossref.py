"""Fill missing directors from screenslate's listings of the same screening.

Some cinemas never say who directed a film (Film at Lincoln Center's data has no directors), and
multi-film programmes ("The Audiovisual Script: …", five Godard shorts) are invisible to TMDB.
screenslate's editors list every film of a programme with its director. For a venue whose fallback is
screenslate, screenings from the primary source that still lack a director after TMDB are matched to
screenslate's screening at the same venue and time (±10 min) with a similar title, and the director —
plus runtime, a single film's year and the format, if missing — is copied over. What the cinema's own
site says is never replaced.

Requests stay small: only the days that have such screenings are fetched, only nearby programmes are
looked up, and responses are cached for 12 hours under data/cache/screenslate/.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import timedelta
from pathlib import Path

from .models import RawPage, Screening, VenueConfig
from .normalize import now_utc_iso, parse_iso, title_norm, end_from_runtime
from .registry import build_fallback

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "cache" / "screenslate"
CACHE_TTL_S = 12 * 3600
TIME_SLACK = timedelta(minutes=10)
API = "https://www.screenslate.com/api/screenings"
BATCH = 40


def title_similarity(a: str, b: str) -> float:
    """Share of the shorter title's words found in the other (0..1), accents and punctuation ignored."""
    ta, tb = set(title_norm(a).split()), set(title_norm(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def director_list(raw: str, limit: int = 4) -> str:
    """One name each, in order: shorts programmes repeat directors across films ("Laird Sutton, Bill
    Chamberlain, Laird Sutton"); more than `limit` names become the first three and "…"."""
    names = []
    for part in re.split(r"\s*,\s*", raw or ""):       # "Joel & Ethan Coen" stays one credit
        if part and title_norm(part) not in {title_norm(n) for n in names}:
            names.append(part.strip())
    return ", ".join(names if len(names) <= limit else names[:3] + ["…"])


def best_match(target: Screening, candidates: list[Screening]) -> Screening | None:
    """The screenslate screening that is `target`: same time (±10 min) and a similar title. A lone
    candidate at that time needs a weaker title match than one of several (multi-screen venues)."""
    t0 = parse_iso(target.start)
    near = [c for c in candidates if abs(parse_iso(c.start) - t0) <= TIME_SLACK]
    if not near:
        return None
    scored = sorted(((title_similarity(target.title, c.title), c) for c in near), key=lambda x: -x[0])
    score, best = scored[0]
    need = 0.34 if len(near) == 1 else 0.6
    if score < need or (len(scored) > 1 and scored[1][0] == score):
        return None                          # too different, or two equally good candidates
    return best


class _Cache:
    def __init__(self, nid: int):
        self.dir = CACHE_DIR
        self.nid = nid
        self.ids_path = self.dir / f"{nid}-ids.json"
        try:
            self.ids = json.loads(self.ids_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            self.ids = {}

    def day(self, date: str) -> str | None:
        p = self.dir / f"{self.nid}-{date}.json"
        if p.exists() and time.time() - p.stat().st_mtime < CACHE_TTL_S:
            return p.read_text(encoding="utf-8")
        return None

    def put_day(self, date: str, body: str) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / f"{self.nid}-{date}.json").write_text(body, encoding="utf-8")

    def record(self, nid: str) -> dict | None:
        hit = self.ids.get(nid)
        return hit["rec"] if hit and time.time() - hit["t"] < CACHE_TTL_S else None

    def put_records(self, recs: list[dict]) -> None:
        now = time.time()
        for r in recs:
            self.ids[str(r.get("nid"))] = {"t": now, "rec": r}
        self.dir.mkdir(parents=True, exist_ok=True)
        self.ids_path.write_text(json.dumps(self.ids, ensure_ascii=False), encoding="utf-8")


def fill_directors_from_screenslate(screenings: list[Screening], venue: VenueConfig, client) -> list[Screening]:
    """Fill directors in place; returns the screenings that changed (so TMDB can use the new director)."""
    fb = venue.fallback or {}
    if fb.get("adapter") != "screenslate" or not fb.get("nid"):
        return []
    targets = [s for s in screenings if not s.director and s.source == "primary"]
    if not targets:
        return []
    ss = build_fallback(venue, client=client)
    cache = _Cache(int(fb["nid"]))

    # 1) one date listing per day that needs it
    pages: list[RawPage] = []
    items_by_day: dict[str, list[dict]] = {}
    for day in sorted({s.day for s in targets}):
        date = day.replace("-", "")
        body = cache.day(date)
        if body is None:
            page = ss.get_page(f"{API}/date", ext="json",
                               params={"_format": "json", "date": date, "field_venue_target_id": fb["nid"]})
            body = page.body
            cache.put_day(date, body)
        try:
            items_by_day[day] = json.loads(body) if body.strip() else []
        except ValueError:
            items_by_day[day] = []
        pages.append(RawPage(url=f"{API}/date?date={date}", body=body, fetched_at=now_utc_iso(), ext="json"))

    # 2) details only for programmes starting near a screening we need
    from .adapters.screenslate import parse_start
    wanted = []
    for day, items in items_by_day.items():
        starts = [parse_iso(s.start) for s in targets if s.day == day]
        for it in items:
            st = parse_start(it, ss.tz)
            if st and any(abs(st - t) <= TIME_SLACK for t in starts):
                wanted.append(str(it.get("nid")))
    wanted = list(dict.fromkeys(wanted))
    records = [r for r in (cache.record(n) for n in wanted) if r]
    missing = [n for n in wanted if not cache.record(n)]
    for i in range(0, len(missing), BATCH):
        page = ss.get_page(f"{API}/id/{'+'.join(missing[i:i + BATCH])}", ext="json", params={"_format": "json"})
        try:
            got = json.loads(page.body) if page.body.strip() else []
        except ValueError:
            got = []
        cache.put_records(got)
        records += got
    pages.append(RawPage(url=f"{API}/id/cached", body=json.dumps(records), fetched_at=now_utc_iso(), ext="json"))

    # 3) match and copy
    ss_rows = ss.parse(pages)
    by_day: dict[str, list[Screening]] = {}
    for r in ss_rows:
        by_day.setdefault(r.day, []).append(r)
    changed = []
    for s in targets:
        m = best_match(s, by_day.get(s.day, []))
        if not m or not m.director:
            continue
        s.director = director_list(m.director)
        if not s.runtime_min and m.runtime_min:
            s.runtime_min = m.runtime_min
            if not s.end:
                s.end = end_from_runtime(parse_iso(s.start), s.runtime_min)
        if not s.year and m.year:
            s.year = m.year
        if not s.format and m.format:
            s.format = m.format
        changed.append(s)
    log.info("[%s] screenslate: %d of %d missing directors filled (%d day listing(s), %d programme(s) looked up)",
             venue.id, len(changed), len(targets), len(items_by_day), len(wanted))
    return changed
