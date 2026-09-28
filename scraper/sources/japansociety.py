"""Japan Society — WordPress custom events endpoint (SOURCES.md §3)."""
from __future__ import annotations

import json
from datetime import datetime

from ..base import BaseScraper
from ..models import RawPage, Screening
from ..normalize import clean_text, iso, make_id, to_local
from ..registry import register

API = "https://japansociety.org/wp-json/events/v1/data"
CATEGORIES = "9127,10825,9194"      # Film, Film Series, Monthly Classics


def parse_js_datetime(date_s: str, time_s: str) -> datetime:
    """'October 7, 2026' + '7:00 pm' -> aware datetime."""
    return to_local(datetime.strptime(f"{date_s.strip()} {time_s.strip().upper()}", "%B %d, %Y %I:%M %p"))


@register("japansociety")
class JapanSocietyScraper(BaseScraper):
    def fetch(self) -> list[RawPage]:
        return [self.get_page(API, ext="json", params={"events_categories": CATEGORIES})]

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        out = []
        for page in pages:
            for ev in json.loads(page.body):
                title = clean_text(ev.get("title"))
                days = ev.get("days") or {}
                # multi_day entries without a time are series/exhibition containers: skip.
                if not title or days.get("type") != "single_day":
                    continue
                cats = [c.get("name") for c in (ev.get("terms") or {}).get("events_categories") or []]
                series = next((c for c in cats if c and c not in ("Film", "Film Series")), None)
                for d in days.get("single_day_events") or []:
                    if not d.get("date") or not d.get("time_start"):
                        continue
                    try:
                        start = parse_js_datetime(d["date"], d["time_start"])
                    except ValueError:
                        continue
                    end = None
                    if d.get("time_end"):
                        try:
                            end = iso(parse_js_datetime(d["date"], d["time_end"]))
                        except ValueError:
                            pass
                    start_s = iso(start)
                    out.append(Screening(
                        id=make_id(self.venue.id, start_s, title),
                        venue_id=self.venue.id,
                        title=title,
                        start=start_s,
                        end=end,
                        day=start.date().isoformat(),
                        series=series,
                        screen="Japan Society",
                        note="Sold out" if ev.get("sold_out") else None,
                        detail_url=ev.get("permalink") or None,
                        scraped_at=page.fetched_at,
                    ))
        return out
