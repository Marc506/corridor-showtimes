"""Squarespace events collections (PLATFORMS.md §5).

    source: {adapter: squarespace, base_url: https://www.maysles.org, collection: calendar}

GET <base_url>/<collection>?format=json lists the current month; `pagination.nextPageUrl`
("?month=october-2026&view=calendar") pages forward. startDate / endDate are epoch milliseconds (UTC).
Only collections whose `collection.typeName` is "events" are schedules — ordinary pages answer the same
URL with typeName "page" and no items.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from ..base import BaseScraper, RequestBudgetExceeded, ScrapeError
from ..models import RawPage, Screening
from ..normalize import clean_text, iso, make_id, smart_title
from . import Candidate, register_adapter

LIKELY = re.compile(r"calendar|events?|screenings?|films?|showtimes?|program|schedule|cinema|now", re.I)


def collection_json(body: str) -> dict | None:
    try:
        data = json.loads(body)
    except ValueError:
        return None
    return data if isinstance(data, dict) and isinstance(data.get("collection"), dict) else None


def is_events(data: dict | None) -> bool:
    return bool(data) and data["collection"].get("typeName") == "events"


def _ms(v) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(v) / 1000, tz=timezone.utc)
    except (TypeError, ValueError):
        return None


@register_adapter("squarespace")
class SquarespaceAdapter(BaseScraper):
    PARAMS = {"base_url": str, "collection": str}
    OPTIONAL_PARAMS = {"months": int}
    DETECT_ORDER = 50

    def fetch(self) -> list[RawPage]:
        url = f"{self.params['base_url'].rstrip('/')}/{self.params['collection'].strip('/')}"
        page = self.get_page(url, ext="json", params={"format": "json"})
        data = collection_json(page.body)
        if not is_events(data):
            raise ScrapeError(f"{url} is not a Squarespace events collection")
        pages = [page]
        for _ in range(int(self.params.get("months", 2))):
            nxt = (data.get("pagination") or {}).get("nextPageUrl")
            if not nxt:
                break
            try:
                page = self.get_page(urljoin(url, nxt) + "&format=json", ext="json")
            except RequestBudgetExceeded:
                break
            data = collection_json(page.body)
            if not is_events(data):
                break
            pages.append(page)
        return pages

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        out = []
        for page in pages:
            data = collection_json(page.body) or {}
            items = (data.get("items") or []) + (data.get("upcoming") or [])
            for it in items:
                title = smart_title(clean_text(it.get("title")))
                start, end = _ms(it.get("startDate")), _ms(it.get("endDate"))
                if not title or not start:
                    continue
                start_s = iso(start, self.tz)
                loc = it.get("location") if isinstance(it.get("location"), dict) else {}
                full = it.get("fullUrl")
                out.append(Screening(
                    id=make_id(self.venue.id, start_s, title), venue_id=self.venue.id, title=title,
                    start=start_s, day=start_s[:10],
                    end=iso(end, self.tz) if end and 0 < (end - start).total_seconds() <= 8 * 3600 else None,
                    screen=clean_text(loc.get("addressTitle")),
                    detail_url=urljoin(self.params["base_url"].rstrip("/") + "/", full.lstrip("/")) if full else None,
                    scraped_at=page.fetched_at))
        return out

    @classmethod
    def detect(cls, probe) -> Candidate | None:
        if not probe.find(r"Static\.SQUARESPACE_CONTEXT|squarespace\.com|static1\.squarespace"):
            return None
        host = urlparse(probe.url).netloc
        paths = []
        user_path = urlparse(probe.url).path.strip("/")
        if user_path and "/" not in user_path:
            paths.append(user_path)
        for u in probe.links():
            p = urlparse(u)
            segs = p.path.strip("/").split("/")
            if p.netloc == host and segs[0] and len(segs) <= 2 and LIKELY.search(segs[0]):
                paths.append(segs[0])                         # /calendar or /calendar/<event>
        sitemap = probe.get(probe.base + "/sitemap.xml")
        if sitemap and sitemap.status == 200:
            for loc in re.findall(r"<loc>([^<]+)</loc>", sitemap.text):
                parts = urlparse(loc).path.strip("/").split("/")
                if len(parts) == 2 and LIKELY.search(parts[0]):
                    paths.append(parts[0])                    # /<collection>/<event-slug>
        base = probe.base
        for seg in list(dict.fromkeys(paths))[:4]:
            r = probe.get(f"{base}/{seg}?format=json")
            if r is None:
                break
            data = collection_json(r.text) if r.status == 200 else None
            if is_events(data):
                return Candidate("squarespace", {"base_url": base, "collection": seg},
                                 ["Squarespace site", f"/{seg} is an events collection "
                                  f"({len(data.get('items') or [])} items this month)"], order=cls.DETECT_ORDER)
        return None
