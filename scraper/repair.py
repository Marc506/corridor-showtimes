"""Repair a broken recipe with Claude:  python -m scraper.repair --venue <id> [--force] | --failed

Fetches the venue's pages once more (or, if that fails, uses today's raw snapshots in data/raw/), asks
recipe_gen to fix the recipe against them, and overwrites scraper/recipes/<id>.yaml only when the
repaired recipe passes. At most one attempt per venue per day (data/repair/<id>.json) unless --force.
`--failed` repairs every recipe venue whose last run was not ok and re-scrapes the ones it fixed;
scripts/refresh.sh runs that when AUTO_REPAIR=1.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

from . import recipe_gen
from .adapters.recipe import RECIPES_DIR, load_recipe, page_urls
from .base import RAW_DIR, ScrapeError
from .models import RawPage
from .normalize import now_utc_iso, today_local
from .registry import ConfigError, build_scraper, load_venues

log = logging.getLogger("scraper.repair")
STATE_DIR = Path(__file__).resolve().parent.parent / "data" / "repair"


def attempted_today(venue_id: str) -> bool:
    f = STATE_DIR / f"{venue_id}.json"
    return f.exists() and json.loads(f.read_text()).get("date") == date.today().isoformat()


def mark(venue_id: str, result: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / f"{venue_id}.json").write_text(json.dumps({"date": date.today().isoformat(), "result": result}))


def snapshot_pages(venue, recipe: dict) -> list[RawPage]:
    """Today's raw files for the venue, paired in order with the URLs the recipe would request."""
    day_dir = RAW_DIR / today_local(venue.timezone).isoformat()
    files = sorted(day_dir.glob(f"{venue.id}.*")) + sorted(day_dir.glob(f"{venue.id}_[0-9]*.*"),
                                                               key=lambda p: int(p.stem.rsplit("_", 1)[1]))
    urls = [u for spec in recipe["pages"] for u, _ in page_urls(spec, today_local(venue.timezone))]
    return [RawPage(url=u, body=f.read_text(encoding="utf-8"), fetched_at=now_utc_iso())
            for u, f in zip(urls, files)]


def repair(venue_id: str, force: bool = False) -> int:
    venues = {v.id: v for v in load_venues()}
    venue = venues.get(venue_id)
    if venue is None or venue.adapter != "recipe":
        print(f"{venue_id}: not a recipe venue", file=sys.stderr)
        return 2
    if not recipe_gen.available():
        print("no Anthropic API key (ANTHROPIC_API_KEY or config/anthropic_key.txt)", file=sys.stderr)
        return 2
    if attempted_today(venue_id) and not force:
        print(f"{venue_id}: already attempted today (use --force)", file=sys.stderr)
        return 0
    ref = venue.source["recipe"]
    old = load_recipe(ref)
    scraper = build_scraper(venue)
    try:
        pages = scraper.fetch()
    except ScrapeError as e:
        log.warning("[%s] fetch failed (%s); using today's raw snapshots", venue_id, e)
        pages = snapshot_pages(venue, old)
    finally:
        scraper.close()
    if not pages:
        mark(venue_id, "no pages")
        print(f"{venue_id}: no pages to repair against", file=sys.stderr)
        return 1
    gen = recipe_gen.generate(venue.name, pages[0].url, pages, venue.id, venue.timezone,
                              horizon_days=venue.horizon_days, previous=old)
    if gen.recipe is None:
        mark(venue_id, "failed")
        print(f"{venue_id}: repair failed after {len(gen.rounds)} round(s): "
              f"{'; '.join(gen.verdict.problems) if gen.verdict else 'no answer'}", file=sys.stderr)
        return 1
    if isinstance(ref, str):
        recipe_gen.save_recipe(venue_id if ref == venue_id else ref, gen.recipe,
                               header=f"# Repaired by python -m scraper.repair on {date.today().isoformat()}.")
        print(f"{venue_id}: recipe repaired — {len(gen.verdict.screenings)} screenings; "
              f"saved {RECIPES_DIR / (ref + '.yaml')}")
    else:
        print(f"{venue_id}: repaired recipe (inline in venues.yaml — paste it in):\n{gen.recipe}")
    mark(venue_id, "ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m scraper.repair", description=__doc__.splitlines()[0])
    ap.add_argument("--venue", action="append", default=[])
    ap.add_argument("--failed", action="store_true", help="every recipe venue whose last run was not ok")
    ap.add_argument("--force", action="store_true", help="ignore the once-a-day limit")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        ids = list(args.venue)
        if args.failed:
            ids += failed_recipe_venues()
        if not ids:
            if not args.failed:
                ap.error("give --venue <id> or --failed")
            return 0
        codes = {v: repair(v, args.force) for v in dict.fromkeys(ids)}
    except ConfigError as e:
        print(e, file=sys.stderr)
        return 2
    fixed = [v for v, code in codes.items() if code == 0 and args.failed]
    if fixed:
        from .run import main as run_main
        run_main([a for v in fixed for a in ("--venue", v)])
    return max(codes.values())


def failed_recipe_venues() -> list[str]:
    from .store import Store
    store = Store()
    try:
        statuses = store.all_statuses()
    finally:
        store.close()
    return [v.id for v in load_venues() if v.enabled and v.adapter == "recipe"
            and statuses.get(v.id) and statuses[v.id].status != "ok"]


if __name__ == "__main__":
    sys.exit(main())
