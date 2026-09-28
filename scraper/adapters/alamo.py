"""Alamo Drafthouse market schedule (PLATFORMS.md §10).

    source: {adapter: alamo, market: nyc, cinema_id: "2103"}    # cinema_id optional: all cinemas in the market

GET https://drafthouse.com/s/mother/v2/schedule/market/<market> — sessions for every cinema in the market
(`showTimeClt` is cinema-local, `cinemaTimeZoneName` names the zone) plus presentations (titles). No
runtimes. Without cinema_id the venue covers the whole market and `screen` names the cinema.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import urlparse

from ..base import BaseScraper
from ..models import RawPage, Screening
from ..normalize import clean_text, iso, make_id, normalize_format, to_local
from . import Candidate, register_adapter

API = "https://drafthouse.com/s/mother/v2/schedule/market/{market}"
SITE = "https://drafthouse.com"
FILM_FORMATS = {"35mm": "35mm", "70mm": "70mm", "16mm": "16mm"}


def schedule(body: str) -> dict | None:
    try:
        data = json.loads(body).get("data")
    except (ValueError, AttributeError):
        return None
    return data if isinstance(data, dict) and "sessions" in data else None


@register_adapter("alamo")
class AlamoAdapter(BaseScraper):
    PARAMS = {"market": str}
    OPTIONAL_PARAMS = {"cinema_id": str}
    DETECT_ORDER = 15

    def fetch(self) -> list[RawPage]:
        return [self.get_page(API.format(market=self.params["market"]), ext="json")]

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        market = self.params["market"]
        only = str(self.params["cinema_id"]) if self.params.get("cinema_id") else None
        out = []
        for page in pages:
            data = schedule(page.body) or {}
            shows = {p.get("slug"): p for p in data.get("presentations") or []}
            cinemas = {c.get("id"): c.get("name") for m in data.get("market") or [] for c in m.get("cinemas") or []}
            for s in data.get("sessions") or []:
                if s.get("isHidden") or s.get("status") == "PAST" or (only and str(s.get("cinemaId")) != only):
                    continue
                pres = shows.get(s.get("presentationSlug")) or {}
                title = clean_text((pres.get("show") or {}).get("title"))
                try:
                    start = to_local(datetime.fromisoformat(s["showTimeClt"]), s.get("cinemaTimeZoneName") or self.tz)
                except (KeyError, TypeError, ValueError):
                    continue
                if not title:
                    continue
                start_s = iso(start, self.tz)
                fmt = FILM_FORMATS.get(s.get("formatSlug") or "") or next(
                    (normalize_format(a.lower()) for a in s.get("sessionAttributeSlugs") or []
                     if a.lower() in FILM_FORMATS), None)
                screen = f"Screen {s['screenNumber']}" if s.get("screenNumber") else None
                if not only and cinemas.get(s.get("cinemaId")):
                    screen = cinemas[s["cinemaId"]] + (f" · {screen}" if screen else "")
                series = clean_text(((pres.get("superTitle") or {}).get("superTitle")))
                slug = s.get("presentationSlug")
                out.append(Screening(
                    id=make_id(self.venue.id, start_s, title), venue_id=self.venue.id, title=title,
                    start=start_s, day=start_s[:10], format=fmt, series=series, screen=screen,
                    note="Sold out" if s.get("status") == "SOLDOUT" else None,
                    detail_url=f"{SITE}/{market}/show/{slug}" if slug else None,
                    ticket_url=f"{SITE}/{market}/show/{slug}?sessionId={s['sessionId']}" if slug and s.get("sessionId") else None,
                    scraped_at=page.fetched_at))
        return out

    @classmethod
    def detect(cls, probe) -> Candidate | None:
        u = urlparse(probe.url)
        if not u.netloc.lower().endswith("drafthouse.com"):
            return None
        parts = [p for p in u.path.split("/") if p]
        if not parts or parts[0] in ("s", "releases"):
            probe.hints.append("alamo_need_market")
            return None
        market = parts[0]
        r = probe.get(API.format(market=market))
        data = schedule(r.text) if r and r.status == 200 else None
        if not data:
            return None
        params = {"market": market}
        evidence = [f"Alamo Drafthouse market '{market}' schedule API ({len(data['sessions'])} sessions)"]
        if len(parts) >= 3 and parts[1] == "theater":
            for m in data.get("market") or []:
                for c in m.get("cinemas") or []:
                    if c.get("slug") == parts[2]:
                        params["cinema_id"] = str(c["id"])
                        evidence.append(f"cinema '{c.get('name')}' id {c['id']}")
        return Candidate("alamo", params, evidence, order=cls.DETECT_ORDER)
