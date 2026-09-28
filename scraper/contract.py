"""The Screening contract every source must meet, checked offline against saved pages.

Used by tests/test_contract.py (every venue with a fixture manifest) and by
``python -m scraper.add --verify <id>`` (after saving a fresh fixture), so a hand-written source, a
recipe written by an agent and an adapter found by the wizard all prove themselves the same way.

A fixture is a directory with a ``fixture.yaml`` manifest::

    fetched_at: "2026-09-25T01:00:00Z"      # when the pages were fetched (anchors dates without a year)
    pages:
      - file: 2026-09.html                   # relative to the manifest
        url: https://example.org/calendar?month=9&year=2026   # what parse() sees as page.url
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from .models import RawPage, Screening, VenueConfig
from .normalize import zone

MANIFEST = "fixture.yaml"

# What each Screening field means — shown to people and agents writing a new source (templates/BRIEF.md.j2).
FIELD_DOCS = [
    ("id", "required", "make_id(venue_id, start, title) — stable across runs", "3f9c0a1b2d4e5f60"),
    ("venue_id", "required", "the venue's id in config/venues.yaml", "roxy"),
    ("title", "required", "programme title as shown; ALL-CAPS sources go through smart_title(); double bills joined with ' + '", "Idlewild"),
    ("start", "required", "ISO 8601 with the venue's UTC offset (iso(dt, tz))", "2026-09-28T19:00:00-04:00"),
    ("day", "required", "local date, always start[:10]", "2026-09-28"),
    ("end", "optional", "ISO 8601 with offset; from the site, or start + runtime (end_from_runtime)", "2026-09-28T21:01:00-04:00"),
    ("director", "optional", "director name(s), comma-separated", "Wong Kar-wai"),
    ("year", "optional", "release year, 1888 to next year", "1997"),
    ("runtime_min", "optional", "minutes, 1–600", "96"),
    ("format", "optional", "normalize_format(): 35mm / 16mm / 70mm / DCP / Digital …", "35mm"),
    ("language", "optional", "spoken language(s) when the site says so (language_from_text); empty = unknown, never guess English", "French, Wolof"),
    ("series", "optional", "series or festival the screening belongs to", "Reel October"),
    ("screen", "optional", "auditorium / room / branch", "Theater 2"),
    ("note", "optional", "Q&A, sold out, intro …", "Sold out"),
    ("detail_url", "optional", "absolute URL of the film's page on the cinema site", "https://example.org/films/idlewild"),
    ("ticket_url", "optional", "absolute URL to buy this showing", "https://example.org/buy/7733"),
    ("source", "set by the pipeline", "leave the default", "primary"),
    ("scraped_at", "required", "page.fetched_at of the page the row came from", "2026-09-28T16:00:00Z"),
]
ABSOLUTE_URL = re.compile(r"^https?://[^/\s]+", re.I)
OFFSET_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?[+-]\d{2}:\d{2}$")
PAST_SLACK_DAYS = 62            # month pages list the whole month, sometimes the previous one too
IN_WINDOW_SHARE = 0.9           # presales (opera, festivals) may legitimately sit beyond the window


@dataclass
class Fixture:
    pages: list[RawPage]
    fetched_at: str
    path: Path

    @property
    def fetched_date(self) -> date:
        return datetime.fromisoformat(self.fetched_at.replace("Z", "+00:00")).date()


def ext_for(name: str) -> str:
    suffix = Path(name).suffix.lower().lstrip(".")
    return {"json": "json", "ics": "ics", "js": "js", "xml": "xml"}.get(suffix, "html")


def load_fixture(directory: Path, manifest: dict | None = None) -> Fixture:
    """Pages listed in <directory>/fixture.yaml (or an explicit manifest dict), in order."""
    directory = Path(directory)
    if manifest is None:
        manifest = yaml.safe_load((directory / MANIFEST).read_text(encoding="utf-8")) or {}
    fetched_at = str(manifest.get("fetched_at") or "")
    if not fetched_at:
        raise ValueError(f"{directory / MANIFEST}: fetched_at is required")
    pages = []
    for item in manifest.get("pages") or []:
        item = {"file": item} if isinstance(item, str) else item
        path = (directory / item["file"]).resolve()
        pages.append(RawPage(url=item.get("url") or f"file://{path}", body=path.read_text(encoding="utf-8"),
                             fetched_at=item.get("fetched_at") or fetched_at, ext=item.get("ext") or ext_for(path.name)))
    return Fixture(pages=pages, fetched_at=fetched_at, path=directory)


def has_fixture(directory: Path) -> bool:
    return (Path(directory) / MANIFEST).exists()


def check_venue(venue_id: str, fixtures_root: Path | None = None) -> list[str]:
    """Contract problems for a venue in config/venues.yaml, using tests/fixtures/<id>/fixture.yaml."""
    from .base import dedupe
    from .registry import ROOT, build_scraper, load_venues
    venue = {v.id: v for v in load_venues()}[venue_id]
    fx = load_fixture((fixtures_root or ROOT / "tests" / "fixtures") / venue_id)
    scraper = build_scraper(venue, client=object())
    rows = dedupe(scraper.parse(fx.pages))
    return check(venue, rows, fx.fetched_date, dedupe(scraper.parse(fx.pages)))


def check(venue: VenueConfig, rows: list[Screening], fetched: date, again: list[Screening] | None = None) -> list[str]:
    """Contract problems (empty list = pass). `again`: a second parse of the same pages (id stability)."""
    problems: list[str] = []
    if not rows:
        return ["parsed 0 screenings"]
    tz = zone(venue.timezone)

    def bad(row: Screening, what: str) -> None:
        if len(problems) < 25:
            problems.append(f"{row.start} {row.title!r}: {what}")

    if again is not None and sorted(r.id for r in rows) != sorted(r.id for r in again):
        problems.append("ids differ between two parses of the same pages")
    lo = fetched - timedelta(days=1)
    hi = fetched + timedelta(days=venue.horizon_days + 60)
    too_old = fetched - timedelta(days=PAST_SLACK_DAYS)
    upcoming = in_window = 0
    for r in rows:
        if not (r.title or "").strip():
            bad(r, "empty title")
        if r.venue_id != venue.id:
            bad(r, f"venue_id {r.venue_id!r} != {venue.id!r}")
        if not OFFSET_ISO.match(r.start or ""):
            bad(r, "start is not ISO 8601 with a UTC offset")
            continue
        start = datetime.fromisoformat(r.start)
        expected = start.replace(tzinfo=None).replace(tzinfo=tz).utcoffset()
        if start.utcoffset() != expected:
            bad(r, f"offset {start.strftime('%z')} does not match {venue.timezone} on that date")
        if r.day != r.start[:10]:
            bad(r, f"day {r.day} != start date")
        if r.end:
            if not OFFSET_ISO.match(r.end):
                bad(r, "end is not ISO 8601 with a UTC offset")
            elif datetime.fromisoformat(r.end) <= start:
                bad(r, "end is not after start")
        for field in ("detail_url", "ticket_url"):
            url = getattr(r, field)
            if url and not ABSOLUTE_URL.match(url):
                bad(r, f"{field} is not an absolute URL: {url}")
        if r.runtime_min is not None and not 1 <= r.runtime_min <= 600:
            bad(r, f"runtime_min {r.runtime_min} outside 1–600")
        if r.year is not None and not 1888 <= r.year <= fetched.year + 1:
            bad(r, f"year {r.year} outside 1888–{fetched.year + 1}")
        d = date.fromisoformat(r.day)
        if d < too_old:
            bad(r, f"{r.day} is more than {PAST_SLACK_DAYS} days before the fetch date {fetched} (wrong year?)")
        if d >= lo:
            upcoming += 1
            in_window += d <= hi
    if not upcoming:
        problems.append(f"no screening on or after {lo} (fetched {fetched})")
    elif in_window < IN_WINDOW_SHARE * upcoming:
        problems.append(f"only {in_window}/{upcoming} upcoming screenings fall before {hi} "
                        f"(horizon_days + 60) — dates probably parsed into the wrong year")
    return problems


def summarize(rows: list[Screening], lang: str = "en") -> str:
    """'Parsed 37 screenings, first 9/29 7:00pm “…”, last 10/19' — the wizard's one-line result."""
    if not rows:
        return "没有解析出任何场次" if lang == "zh" else "Parsed no screenings"
    first, last = min(rows, key=lambda r: r.start), max(rows, key=lambda r: r.start)
    st = datetime.fromisoformat(first.start)
    when = f"{st.month}/{st.day} {st.strftime('%I:%M%p').lstrip('0').lower()}"
    ld = date.fromisoformat(last.day)
    if lang == "zh":
        return f"解析出 {len(rows)} 场，最早 {when}《{first.title}》，最晚 {ld.month}/{ld.day}"
    return f"Parsed {len(rows)} screenings, first {when} “{first.title}”, last {ld.month}/{ld.day}"
