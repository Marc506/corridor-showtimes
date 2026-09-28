"""CLI entry point.

    python -m scraper.run                          # all enabled venues, then export
    python -m scraper.run --venue metrograph       # one venue
    python -m scraper.run --venue bam --dry-run    # print parsed results, don't write
    python -m scraper.run --venue filmforum --parse-fixture tests/fixtures/filmforum/now_playing.html
    python -m scraper.run --venue moma --source fallback   # skip the primary, use venues.yaml `fallback:`
"""
from __future__ import annotations

import argparse
import os
import re
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .base import HttpClient, dedupe
from .models import RawPage, Screening, VenueConfig, VenueStatus
from .normalize import now_utc_iso, today_local
from .registry import ConfigError, build_fallback, build_scraper, load_venues
from .language import TmdbLanguage, fill_languages, load_token, title_hints
from .store import Store

log = logging.getLogger("scraper.run")


def validate(venue: VenueConfig, screenings: list[Screening], status: VenueStatus,
             prev: VenueStatus | None, today: date | None = None) -> tuple[list[Screening], VenueStatus]:
    """Drop out-of-window rows, apply horizon, and turn an empty result into a failure."""
    if status.status != "ok":
        return screenings, status
    today = today or today_local(venue.timezone)
    lo = (today - timedelta(days=1)).isoformat()
    hi_valid = (today + timedelta(days=venue.horizon_days + 60)).isoformat()
    hi_horizon = (today + timedelta(days=venue.horizon_days)).isoformat()

    kept, bad = [], []
    for s in screenings:
        if s.day < lo:
            continue                    # past days on month/week pages are expected
        if s.day > hi_valid:
            bad.append(s)
        elif s.day <= hi_horizon:
            kept.append(s)
    if bad:
        log.warning("[%s] dropped %d out-of-range screenings (e.g. %s %r)",
                    venue.id, len(bad), bad[0].start, bad[0].title)

    if not kept and not venue.allow_empty:
        return [], VenueStatus(venue.id, "failed", error="parsed 0 screenings", source=status.source)
    if prev and prev.count and len(kept) < prev.count * 0.3:
        log.warning("[%s] count dropped sharply: %d -> %d (page structure changed?)",
                    venue.id, prev.count, len(kept))
    status.count = len(kept)
    status.horizon_end = max((s.day for s in kept), default=None)
    return kept, status


def primary_cooldown_left(venue: VenueConfig, store: Store | None) -> float | None:
    """Hours left before retrying a primary that failed recently (venues.yaml primary_cooldown_h).
    Lets MoMA try its browser path ~once a day instead of stalling on Cloudflare every run."""
    hours = float(venue.extra.get("primary_cooldown_h") or 0)
    failed_at = store.primary_failed_at(venue.id) if store and hours else None
    if not failed_at:
        return None
    age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(failed_at.replace("Z", "+00:00"))).total_seconds() / 3600
    return hours - age_h if age_h < hours else None


def _last_primary_error(prev: VenueStatus | None) -> str | None:
    """Original primary failure text, without our own 'primary …' wrappers (avoids nesting)."""
    if not prev or not prev.error:
        return None
    m = re.search(r"(?:last failure|primary failed): (.*?)(?:; [\w-]+ failed:.*)?$", prev.error)
    return m.group(1) if m else prev.error


def run_venue(venue: VenueConfig, store: Store | None, client: HttpClient, dry_run: bool,
              force_source: str | None = None, tmdb=None, hints: dict | None = None) -> VenueStatus:
    """force_source: None (primary, then fallback), "primary" (no fallback), "fallback" (skip the primary).
    "screenslate" is accepted as the v1 name of "fallback"."""
    if force_source == "screenslate":
        force_source = "fallback"
    prev = store.get_status(venue.id) if store else None
    screenings, status = [], VenueStatus(venue.id, "failed")
    primary_result = "skipped"
    cooling = primary_cooldown_left(venue, store) if force_source is None else None
    if force_source == "fallback":
        why = "primary skipped (--source fallback)"
    elif cooling:
        why = f"primary in cooldown ({cooling:.0f}h left); last failure: {_last_primary_error(prev)}"
        log.info("[%s] primary failed recently — skipping it for %.0fh more (primary_cooldown_h)", venue.id, cooling)
    else:
        screenings, status = build_scraper(venue, client=client).run(save_raw=True)
        screenings, status = validate(venue, screenings, status, prev)
        primary_result = "ok" if status.status == "ok" else "failed"
        why = f"primary failed: {status.error}"

    # Fallback: only when the primary didn't deliver, and only for venues that configure one (§5.4).
    fallback = build_fallback(venue, client=client) if status.status != "ok" and force_source != "primary" else None
    if fallback is not None:
        name = venue.fallback["adapter"]
        log.warning("[%s] %s — using %s", venue.id, why, name)
        screenings, status = fallback.run(save_raw=True)
        screenings, status = validate(venue, screenings, status, prev)
        for s in screenings:
            if s.source == "primary":
                s.source = name
        status.source = name
        status.error = why if status.status == "ok" else f"{why}; {name} failed: {status.error}"
    elif status.status != "ok" and primary_result == "skipped":
        status.error = why

    if screenings:
        fill_languages(screenings, venue, tmdb, hints)

    if dry_run:
        print_screenings(screenings)
        log.info("[%s] %s: %d screenings (dry run, nothing written)", venue.id, status.status, len(screenings))
        return status
    if status.status == "ok":
        status = store.apply_success(venue.id, screenings, status, primary_result, tz=venue.timezone)
    else:
        status = store.apply_failure(venue.id, status, primary_result, tz=venue.timezone)
    log.info("[%s] %s: %d future screenings, horizon %s%s", venue.id, status.status, status.count,
             status.horizon_end, f" — {status.error}" if status.error else "")
    return status


LOCK_PATH = Path(__file__).resolve().parent.parent / "data" / ".run.lock"


def acquire_run_lock():
    """One writing run at a time (manual runs and the launchd job share the DB and browser profile).
    Returns the open lock file (keep a reference), or False if another run holds it. Released on exit."""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    f = open(LOCK_PATH, "a+")
    try:
        try:
            import fcntl
        except ImportError:                          # Windows
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:                                  # BlockingIOError on POSIX, PermissionError on Windows
        f.close()
        return False
    f.seek(0)
    f.truncate()
    f.write(str(os.getpid()))
    f.flush()
    return f


def print_screenings(screenings: list[Screening]) -> None:
    for s in screenings:
        meta = ", ".join(str(x) for x in (s.director, s.year, f"{s.runtime_min}m" if s.runtime_min else None,
                                          s.format, s.language) if x)
        print(f"{s.start}  {s.title}" + (f" ({meta})" if meta else "") +
              (f"  [{s.screen}]" if s.screen else "") + (f"  <{s.note}>" if s.note else ""))


def parse_fixture(venue: VenueConfig, path: Path) -> None:
    ext = "json" if path.suffix == ".json" else "html"
    page = RawPage(url=f"file://{path.resolve()}", body=path.read_text(encoding="utf-8"),
                   fetched_at=now_utc_iso(), ext=ext)
    screenings = dedupe(build_scraper(venue).parse([page]))
    print_screenings(screenings)
    print(f"-- {len(screenings)} screenings", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m scraper.run")
    ap.add_argument("--venue", action="append", help="venue id (repeatable); default: all enabled")
    ap.add_argument("--dry-run", action="store_true", help="print parsed results, don't write DB")
    ap.add_argument("--parse-fixture", type=Path, help="parse a saved page offline (needs --venue)")
    ap.add_argument("--no-export", action="store_true", help="skip writing site/data.js")
    ap.add_argument("--source", choices=["primary", "fallback", "screenslate"],
                    help="force one source: 'fallback' skips the primary, 'primary' disables the fallback "
                         "('screenslate' = 'fallback')")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    try:
        venues = load_venues()
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 2
    by_id = {v.id: v for v in venues}
    if args.venue:
        unknown = [v for v in args.venue if v not in by_id]
        if unknown:
            ap.error(f"unknown venue(s): {', '.join(unknown)}; known: {', '.join(by_id)}")
        selected = [by_id[v] for v in args.venue]
    else:
        selected = [v for v in venues if v.enabled]

    if args.parse_fixture:
        if len(selected) != 1 or not args.venue:
            ap.error("--parse-fixture needs exactly one --venue")
        parse_fixture(selected[0], args.parse_fixture)
        return 0

    lock = None if args.dry_run else acquire_run_lock()
    if lock is False:
        log.warning("another scraper run is in progress — skipping (lock: %s)", LOCK_PATH)
        return 0

    client = HttpClient()
    store = None if args.dry_run else Store()
    token = load_token()
    tmdb = TmdbLanguage(token) if token else None
    hints = title_hints(store.title_years()) if store else {}
    if not tmdb:
        log.info("no TMDB token (config/tmdb_token.txt) — languages only from venue sites")
    results = []
    try:
        for v in selected:
            results.append(run_venue(v, store, client, args.dry_run, force_source=args.source, tmdb=tmdb,
                                     hints=hints))
        if store and not args.no_export:
            from .export import export
            export(store)
    finally:
        client.close()
        if store:
            store.close()
    bad = [s.venue_id for s in results if s.status != "ok"]
    if bad:
        log.warning("venues not ok: %s", ", ".join(bad))
    return 0


if __name__ == "__main__":
    sys.exit(main())
