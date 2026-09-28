"""SQLite -> data/showtimes.json + site/data.js (window.CINEMA_DATA)."""
from __future__ import annotations

import json
import logging
from datetime import timedelta
from pathlib import Path

from .normalize import now_utc_iso, today_local
from .registry import load_venues
from .store import Store

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
JSON_OUT = ROOT / "data" / "showtimes.json"
JS_OUT = ROOT / "site" / "data.js"

DROP_FIELDS = {"scraped_at", "first_seen", "last_seen"}


def build_payload(store: Store) -> dict:
    statuses = store.all_statuses()
    venues = []
    for v in load_venues():
        st = statuses.get(v.id)
        venues.append({
            "id": v.id, "name": v.name, "short": v.short or v.id[:3].upper(),
            "color": v.color, "region": v.region, "city": v.region, "timezone": v.timezone,
            "website": v.website, "adapter": v.adapter if v.adapter != "custom" else None,
            "status": "disabled" if not v.enabled else (st.status if st else "failed"),
            "fetched_at": st.fetched_at if st else None,
            "count": st.count if st else 0,
            "horizon_end": st.horizon_end if st else None,
            "error": st.error if st else ("not scraped yet" if v.enabled else None),
            "source": st.source if st else None,
        })
    known = {v["id"] for v in venues}

    since = (today_local() - timedelta(days=1)).isoformat()
    screenings, days = [], {}
    for row in store.screenings_since(since):
        if row["venue_id"] not in known:
            continue
        s = {k: v for k, v in row.items() if k not in DROP_FIELDS}
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
