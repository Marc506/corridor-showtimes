"""SQLite -> data/showtimes.json + site/data.js (window.CINEMA_DATA)."""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import timedelta
from pathlib import Path

from .language import search_title
from .normalize import now_utc_iso, title_norm, today_local
from .registry import load_venues
from .store import Store

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
JSON_OUT = ROOT / "data" / "showtimes.json"
JS_OUT = ROOT / "site" / "data.js"

DROP_FIELDS = {"scraped_at", "first_seen", "last_seen"}

# The "Limited screenings" filter (限定放映) hides new films in their regular run. A screening is in a regular run when the film is
# new (this year or last), it is not a special event, and the same cinema shows it often:
#   * outside any series: 3+ times (a small single-screen house runs a new film once a day);
#   * inside a series or festival: 8+ times at 2+ a day. A festival film plays a gala night and then once a day
#     around town (Behemoth! at NYFF: 8 shows, 1.6 a day); a festival label on a theatrical run does not change
#     what it is (Fatherland at FLC: 38 shows, 3.8 a day).
# And only a film that has opened widely is hidden. Any of:
#   * it is in a run at 2+ of the cinemas here;
#   * a reference chain (venues with `reference: true`, Alamo Drafthouse's NYC and Boston schedules, never shown)
#     plays it 8+ times in one city — a run, not one of its special screenings (those are 1-5 shows);
#   * it reached streaming within two weeks of opening (Screening.streaming: Netflix's Animals).
# A run at one cinema of a film that is none of these is an exclusive engagement (Film Forum's My Undesirable
# Friends) and stays. Old films are never hidden however often they play, and a film without a year is kept.
RUN_WINDOW_DAYS = 14                  # counts include the last two weeks, so a run's last shows stay hidden
RUN_SHOWS = 3
RUN_SHOWS_IN_SERIES = 8
RUN_DAILY_IN_SERIES = 2.0
RUN_VENUES = 2
REFERENCE_SHOWS = 8
SPECIAL_NOTE = re.compile(r"Q\s*&\s*A|in[- ]person|introduc|conversation|discussion|premiere|preview|"
                          r"live (?:score|music|musical)|panel|\bwith (?:director|filmmaker)", re.I)


def film_key(title: str) -> str:
    """One key per film across cinemas: 'Tony (2026)' ~ 'Tony', 'Digger in VistaVision' ~ 'Digger'."""
    return title_norm(search_title(title) or title)


def regular_runs(rows: list[dict], recent: list[dict], this_year: int, reference: set[str] = frozenset()) -> set[str]:
    """Ids of `rows` that are new films in a regular run that has opened widely (see RUN_SHOWS and the rules
    above). `recent` is every stored screening from RUN_WINDOW_DAYS ago on, the reference venues' included,
    used to count how often each cinema shows each film."""
    shows: Counter = Counter()
    days: dict[tuple, set] = {}
    for r in recent:
        k = (r["venue_id"], film_key(r["title"]))
        shows[k] += 1
        days.setdefault(k, set()).add(r["day"])
    at_chain = {key for (vid, key), n in shows.items() if vid in reference and n >= REFERENCE_SHOWS}

    def in_run(r) -> bool:
        if not r.get("year") or r["year"] < this_year - 1:
            return False
        k = (r["venue_id"], film_key(r["title"]))
        n = shows[k]
        if r.get("series"):
            return n >= RUN_SHOWS_IN_SERIES and n / len(days.get(k) or {1}) >= RUN_DAILY_IN_SERIES
        return n >= RUN_SHOWS

    running = [r for r in rows if in_run(r)]
    venues: dict[str, set] = {}
    for r in running:
        venues.setdefault(film_key(r["title"]), set()).add(r["venue_id"])
    def wide(r) -> bool:
        key = film_key(r["title"])
        return len(venues[key]) >= RUN_VENUES or key in at_chain or bool(r.get("streaming"))

    return {r["id"] for r in running if wide(r) and not SPECIAL_NOTE.search(r.get("note") or "")}


def build_payload(store: Store) -> dict:
    statuses = store.all_statuses()
    venues = []
    configured = load_venues()
    reference = {v.id for v in configured if v.reference}
    for v in configured:
        if v.reference:
            continue
        st = statuses.get(v.id)
        venues.append({
            "id": v.id, "name": v.name, "short": v.short or v.id[:3].upper(),
            "color": v.color, "region": v.region, "city": v.region, "timezone": v.timezone,
            "website": v.website, "adapter": v.adapter if v.adapter != "custom" else None,
            "location": v.location,
            "status": "disabled" if not v.enabled else (st.status if st else "failed"),
            "fetched_at": st.fetched_at if st else None,
            "count": st.count if st else 0,
            "horizon_end": st.horizon_end if st else None,
            "error": st.error if st else ("not scraped yet" if v.enabled else None),
            "source": st.source if st else None,
        })
    known = {v["id"] for v in venues}

    since = (today_local() - timedelta(days=1)).isoformat()
    rows = [r for r in store.screenings_since(since) if r["venue_id"] in known]
    recent = store.screenings_since((today_local() - timedelta(days=RUN_WINDOW_DAYS)).isoformat())
    runs = regular_runs(rows, recent, today_local().year, reference)
    screenings, days = [], {}
    for row in rows:
        s = {k: v for k, v in row.items() if k not in DROP_FIELDS}
        s["run"] = row["id"] in runs
        screenings.append(s)
        days.setdefault(s["day"], []).append(s["id"])

    return {"generated_at": now_utc_iso(), "venues": venues,
            "screenings": screenings, "days": dict(sorted(days.items()))}


def export(store: Store | None = None) -> dict:
    own = store is None
    store = store or Store()
    try:
        payload = build_payload(store)
    finally:
        if own:
            store.close()
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    JS_OUT.parent.mkdir(parents=True, exist_ok=True)
    JS_OUT.write_text("window.CINEMA_DATA = " + json.dumps(payload, ensure_ascii=False) + ";\n",
                      encoding="utf-8")
    log.info("exported %d screenings across %d days -> %s", len(payload["screenings"]),
             len(payload["days"]), JS_OUT)
    return payload


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    export()
