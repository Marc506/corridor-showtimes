"""WordPress "My Calendar" plugin REST API (PLATFORMS.md §10).

    source: {adapter: wp-my-calendar, base_url: https://www.trylon.org}

GET <base_url>/wp-json/my-calendar/v1/events?from=YYYY-MM-DD&to=YYYY-MM-DD
    {"2026-09-28": [{"event_title", "occur_begin": "2026-09-28 19:00:00", "event_link", "event_desc"}]}
Times are venue-local. Descriptions often start with "1975, 86m, French w/English subtitles) dir …".
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from bs4 import BeautifulSoup

from ..base import BaseScraper, ScrapeError
from ..models import RawPage, Screening
from ..normalize import clean_text, end_from_runtime, iso, language_from_text, make_id, to_local, today_local
from . import Candidate, register_adapter

API = "/wp-json/my-calendar/v1/events"
META = re.compile(r"\b((?:18|19|20)\d{2}),\s*(\d{2,3})\s*m(?:in)?\b")
DIRECTOR = re.compile(r"\bdir(?:ected by|\.)?\s+([A-Z][^.;,()]+?)(?=\s+w/|\s+with\b|[.;,()]|$)")


def calendar_json(body: str) -> dict | None:
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if isinstance(data, dict) and all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", k) for k in data):
        return data
    return None


def describe(html: str | None) -> dict:
    text = clean_text(BeautifulSoup(html or "", "lxml").get_text(" ")) or ""
    out: dict = {}
    if m := META.search(text):
        out["year"], out["runtime_min"] = int(m.group(1)), int(m.group(2))
    if m := DIRECTOR.search(text):
        out["director"] = m.group(1).strip()
    lang = re.sub(r"\bw/\s*", "with ", text)
    lang = re.sub(r"(\b[A-Z][a-z]+(?:,? (?:and )?[A-Z][a-z]+)*) with English subtitles", r"In \1 with English subtitles", lang)
    out["language"] = language_from_text(lang)
    return out


@register_adapter("wp-my-calendar")
class WpMyCalendarAdapter(BaseScraper):
    PARAMS = {"base_url": str}
    DETECT_ORDER = 45

    def fetch(self) -> list[RawPage]:
        start = today_local(self.tz)
        page = self.get_page(self.params["base_url"].rstrip("/") + API, ext="json", params={
            "from": start.isoformat(), "to": (start + timedelta(days=self.venue.horizon_days)).isoformat()})
        if calendar_json(page.body) is None:
            raise ScrapeError("My Calendar API did not return JSON")
        return [page]

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        out = []
        for page in pages:
            for events in (calendar_json(page.body) or {}).values():
                for ev in events or []:
                    title = clean_text(ev.get("event_title"))
                    try:
                        start = to_local(datetime.fromisoformat(ev["occur_begin"]), self.tz)
                    except (KeyError, TypeError, ValueError):
                        continue
                    if not title:
                        continue
                    meta = describe(ev.get("event_desc"))
                    start_s = iso(start, self.tz)
                    link = clean_text(ev.get("event_link"))
                    out.append(Screening(
                        id=make_id(self.venue.id, start_s, title), venue_id=self.venue.id, title=title,
                        start=start_s, day=start_s[:10], end=end_from_runtime(start, meta.get("runtime_min")),
                        director=meta.get("director"), year=meta.get("year"), runtime_min=meta.get("runtime_min"),
                        language=meta.get("language"), detail_url=link or None,
                        ticket_url=clean_text(ev.get("event_tickets")) or None, scraped_at=page.fetched_at))
        return out

    @classmethod
    def detect(cls, probe) -> Candidate | None:
        if not probe.find(r"my-calendar"):
            return None
        for root in probe.wp_roots()[:1]:
            r = probe.get(root + "my-calendar/v1/events")
            if r and r.status == 200 and calendar_json(r.text) is not None:
                n = sum(len(v or []) for v in calendar_json(r.text).values())
                return Candidate("wp-my-calendar", {"base_url": root[: -len("/wp-json/")]},
                                 ["My Calendar plugin", f"{root}my-calendar/v1/events returns {n} events"],
                                 order=cls.DETECT_ORDER)
        return None
