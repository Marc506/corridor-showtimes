"""Wix Events: the event list a Wix site embeds in its own page (PLATFORMS.md §14).

    source: {adapter: wix, pages: ['https://www.lightboxfilmcenter.org/events-1']}

A Wix page with an Events widget ships the widget's data in `<script id="wix-warmup-data">`:
appsWarmupData.<app>.<widget>.events.events[] with `title`, `slug`, `description` (a one-line
tagline), `location` {name, address}, `scheduling.config` {startDate, endDate (UTC), timeZoneId,
recurrences.occurrences[]} and `registration` (`external.registration` = the ticket link when tickets are
sold elsewhere). A page can hold several widgets (upcoming / past); events are de-duplicated by id, and
showings that started more than a day before the page was fetched are skipped. No extra requests: one GET
per configured page.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from ..base import BaseScraper
from ..models import RawPage, Screening
from ..normalize import clean_text, iso, make_id
from . import Candidate, register_adapter

WARMUP = re.compile(r'<script[^>]*id="wix-warmup-data"[^>]*>(.*?)</script>', re.S)
LIKELY = re.compile(r"calendar|events?|screenings?|films?|showtimes?|program|schedule|cinema|now", re.I)


def warmup_events(html: str) -> list[dict]:
    """Every Wix Events record embedded in the page (any app, any widget), de-duplicated by id."""
    m = WARMUP.search(html or "")
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return []
    found: dict[str, dict] = {}

    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("scheduling"), dict) and o.get("title") and o.get("id"):
                found.setdefault(o["id"], o)
                return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(data.get("appsWarmupData") or data)
    return list(found.values())


def _utc(s) -> datetime | None:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def occurrences(event: dict) -> list[tuple[datetime, datetime | None]]:
    """(start, end) of each showing: the recurrence list when there is one, else the event's own dates."""
    cfg = (event.get("scheduling") or {}).get("config") or {}
    if cfg.get("scheduleTbd"):
        return []
    occ = ((cfg.get("recurrences") or {}).get("occurrences")) or [cfg]
    out = []
    for o in occ:
        start = _utc(o.get("startDate"))
        if start:
            end = _utc(o.get("endDate"))
            out.append((start, end if end and 0 < (end - start).total_seconds() <= 8 * 3600 else None))
    return out


def _now() -> datetime:
    return datetime.now(timezone.utc)


def upcoming_count(html: str, now: datetime) -> int:
    return sum(1 for e in warmup_events(html) for s, _ in occurrences(e) if s >= now)


@register_adapter("wix")
class WixAdapter(BaseScraper):
    PARAMS = {"pages": list}
    DETECT_ORDER = 60

    def fetch(self) -> list[RawPage]:
        return [self.get_page(u) for u in self.params["pages"]]

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        out, seen = [], set()
        for page in pages:
            since = _utc(page.fetched_at) - timedelta(days=1)
            site = "{0.scheme}://{0.netloc}".format(urlparse(page.url))
            for ev in warmup_events(page.body):
                title = clean_text(ev.get("title"))
                if not title:
                    continue
                slug = ev.get("slug") or ""
                own = re.search(rf'href="([^"]*/{re.escape(slug)})"', page.body) if slug else None
                detail = own.group(1) if own else (f"{site}/event-details/{slug}" if slug else None)
                reg = ev.get("registration") or {}
                external = (reg.get("external") or {}).get("registration")
                # Wix's own sold-out flag means nothing when tickets are sold elsewhere
                sold_out = not external and bool((reg.get("ticketing") or {}).get("soldOut"))
                note = "; ".join(x for x in (clean_text(ev.get("description")), "Sold out" if sold_out else None) if x)
                place = clean_text((ev.get("location") or {}).get("name"))
                for start, end in occurrences(ev):
                    if start < since:
                        continue
                    start_s = iso(start, self.tz)
                    sid = make_id(self.venue.id, start_s, title)
                    if sid in seen:
                        continue
                    seen.add(sid)
                    out.append(Screening(
                        id=sid, venue_id=self.venue.id, title=title, start=start_s, day=start_s[:10],
                        end=iso(end, self.tz) if end else None, screen=place, note=note or None,
                        detail_url=detail, ticket_url=external or detail, scraped_at=page.fetched_at))
        return out

    @classmethod
    def detect(cls, probe) -> Candidate | None:
        if not probe.find(r'id="wix-warmup-data"'):
            return None
        now = _now()
        scores = {r.final_url or r.url: upcoming_count(r.text, now) for r in probe.pages}
        host = urlparse(probe.url).netloc
        paths = []
        for u in probe.links():
            p = urlparse(u)
            segs = p.path.strip("/").split("/")
            if p.netloc == host and len(segs) == 1 and segs[0] and LIKELY.search(segs[0]):
                paths.append(f"{probe.base}/{segs[0]}")       # /events, /events-1, /calendar …
        for url in list(dict.fromkeys(paths))[:4]:
            if url in scores:
                continue
            r = probe.get(url)
            if r is None:
                break
            if r.status == 200:
                scores[url] = upcoming_count(r.text, now)
        best = max(scores.items(), key=lambda kv: kv[1], default=(None, 0))
        if not best[1]:
            return None
        return Candidate("wix", {"pages": [best[0]]},
                         ["Wix site with the Events app", f"{best[1]} upcoming showings embedded in {best[0]}"],
                         order=cls.DETECT_ORDER)
