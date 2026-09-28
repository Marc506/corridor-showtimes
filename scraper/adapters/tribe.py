"""WordPress "The Events Calendar" (Tribe) REST API (PLATFORMS.md §4).

    source: {adapter: tribe, base_url: https://uniondocs.org, categories: [screenings-events]}

GET <base_url>/wp-json/tribe/events/v1/events?per_page=50&start_date=YYYY-MM-DD, following
`next_rest_url`. Titles and costs are HTML-entity encoded (sometimes with <br>); every event carries
its own `timezone`. Some sites answer this path with an HTML page (200) — only JSON with an `events`
key counts. Workshops spanning several days and all-day events are not screenings and are skipped.
"""
from __future__ import annotations

import json
from datetime import datetime

from bs4 import BeautifulSoup

from ..base import BaseScraper, RequestBudgetExceeded, ScrapeError
from ..models import RawPage, Screening
from ..normalize import clean_text, iso, make_id, to_local, today_local
from . import Candidate, register_adapter

API = "/wp-json/tribe/events/v1/events"
MAX_SPAN_H = 8


def html_text(s: str | None) -> str | None:
    return clean_text(BeautifulSoup(s, "lxml").get_text(" ")) if s and "<" in s else clean_text(s)


def api_json(body: str) -> dict | None:
    try:
        data = json.loads(body)
    except ValueError:
        return None
    return data if isinstance(data, dict) and "events" in data else None


@register_adapter("tribe")
class TribeAdapter(BaseScraper):
    PARAMS = {"base_url": str}
    OPTIONAL_PARAMS = {"categories": list}
    DETECT_ORDER = 40

    def fetch(self) -> list[RawPage]:
        base = self.params["base_url"].rstrip("/")
        page = self.get_page(base + API, ext="json", params={
            "per_page": 50, "start_date": today_local(self.tz).isoformat(),
            **({"categories": ",".join(self.params["categories"])} if self.params.get("categories") else {})})
        data = api_json(page.body)
        if data is None:
            raise ScrapeError("The Events Calendar API did not return JSON")
        pages = [page]
        while data.get("next_rest_url"):
            try:
                page = self.get_page(data["next_rest_url"], ext="json")
            except RequestBudgetExceeded:
                break
            data = api_json(page.body)
            if data is None:
                break
            pages.append(page)
        return pages

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        wanted = set(self.params.get("categories") or [])
        out = []
        for page in pages:
            for ev in (api_json(page.body) or {}).get("events") or []:
                cats = {c.get("slug") for c in ev.get("categories") or []}
                if wanted and not cats & wanted:
                    continue
                if ev.get("all_day"):
                    continue
                title = html_text(ev.get("title"))
                try:
                    start = to_local(datetime.fromisoformat(ev["start_date"]), ev.get("timezone") or self.tz)
                    end = to_local(datetime.fromisoformat(ev["end_date"]), ev.get("timezone") or self.tz) \
                        if ev.get("end_date") else None
                except (KeyError, TypeError, ValueError):
                    continue
                if not title:
                    continue
                if end and (end - start).total_seconds() > MAX_SPAN_H * 3600:
                    continue                                     # multi-day workshop / exhibition
                start_s = iso(start, self.tz)
                venue = ev.get("venue") if isinstance(ev.get("venue"), dict) else {}
                cost = html_text(ev.get("cost"))
                out.append(Screening(
                    id=make_id(self.venue.id, start_s, title), venue_id=self.venue.id, title=title,
                    start=start_s, day=start_s[:10],
                    end=iso(end, self.tz) if end and end > start else None,
                    screen=html_text(venue.get("venue")) if venue.get("venue") else None,
                    note=cost if cost and len(cost) < 40 else None,
                    detail_url=ev.get("url") or None, scraped_at=page.fetched_at))
        return out

    @classmethod
    def detect(cls, probe) -> Candidate | None:
        if not probe.find(r"tribe-events|tribe-common|/tribe/events/"):
            return None
        for root in probe.wp_roots()[:1]:
            r = probe.get(root + "tribe/events/v1/events?per_page=1")
            if r and r.status == 200 and r.is_json and api_json(r.text) is not None:
                base = root[: -len("/wp-json/")]
                return Candidate("tribe", {"base_url": base},
                                 ["The Events Calendar markup", f"{root}tribe/events/v1/events returns JSON "
                                  f"({api_json(r.text).get('total', '?')} upcoming events)"], order=cls.DETECT_ORDER)
        return None
