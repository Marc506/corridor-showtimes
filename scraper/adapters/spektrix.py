"""Spektrix public API, "Web User mode" (PLATFORMS.md §7).

    source: {adapter: spektrix, client: tynesidecinema}

GET https://system.spektrix.com/<client>/api/v3/events?instanceStart_from=…&instanceStart_to=…
GET https://system.spektrix.com/<client>/api/v3/events/<id>/instances       (one per event)
`start` is venue-local. The bulk /instances endpoint timed out when tested, so instances are read per
event, as many as max_requests_per_run allows.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from ..base import BaseScraper, RequestBudgetExceeded
from ..models import RawPage, Screening
from ..normalize import clean_text, end_from_runtime, iso, make_id, to_local, today_local
from . import Candidate, register_adapter

BASE = "https://system.spektrix.com/{client}/api/v3"
CLIENT = re.compile(r"system\.spektrix\.com/([a-z0-9_-]+)/", re.I)
INSTANCES = re.compile(r"/events/([^/]+)/instances")


@register_adapter("spektrix")
class SpektrixAdapter(BaseScraper):
    PARAMS = {"client": str}
    DETECT_ORDER = 65

    def fetch(self) -> list[RawPage]:
        base = BASE.format(client=self.params["client"])
        start = today_local(self.tz)
        events = self.get_page(base + "/events", ext="json", params={
            "instanceStart_from": f"{start.isoformat()}T00:00",
            "instanceStart_to": f"{(start + timedelta(days=self.venue.horizon_days)).isoformat()}T00:00"})
        pages = [events]
        for ev in json.loads(events.body):
            try:
                pages.append(self.get_page(f"{base}/events/{ev['id']}/instances", ext="json"))
            except RequestBudgetExceeded:
                break
        return pages

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        events = {}
        for p in pages:
            if not INSTANCES.search(p.url):
                events.update({e["id"]: e for e in json.loads(p.body) if e.get("id")})
        out = []
        for p in pages:
            if not INSTANCES.search(p.url):
                continue
            for inst in json.loads(p.body):
                ev = events.get((inst.get("event") or {}).get("id")) or {}
                title = clean_text(ev.get("name"))
                if not title or inst.get("cancelled"):
                    continue
                try:
                    start = to_local(datetime.fromisoformat(inst["start"]), self.tz)
                except (KeyError, TypeError, ValueError):
                    continue
                runtime = ev.get("duration") if isinstance(ev.get("duration"), int) and 0 < ev["duration"] <= 600 else None
                start_s = iso(start, self.tz)
                out.append(Screening(
                    id=make_id(self.venue.id, start_s, title), venue_id=self.venue.id, title=title,
                    start=start_s, day=start_s[:10], end=end_from_runtime(start, runtime),
                    director=clean_text(ev.get("attribute_Director")), runtime_min=runtime,
                    format="35mm" if inst.get("attribute_35mmScreening") else None,
                    note=None if inst.get("isOnSale", True) else "Not on sale",
                    detail_url=ev.get("webUrl") or None, scraped_at=p.fetched_at))
        return out

    @classmethod
    def detect(cls, probe) -> Candidate | None:
        clients = [c for c in probe.findall(CLIENT.pattern) if c.lower() not in ("api", "system")]
        if not clients:
            return None
        return Candidate("spektrix", {"client": clients[0]}, [f"Spektrix client '{clients[0]}' linked from the site"],
                         order=cls.DETECT_ORDER)
