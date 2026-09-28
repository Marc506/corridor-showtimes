"""Eventive (PLATFORMS.md §6).

    source: {adapter: eventive, bucket: 6a4fa3acb024f1f9ffa9cb70, api_key: <32 hex>, site: cornellcinema}

GET https://api.eventive.org/event_buckets/<bucket>/events with header `x-api-key: <key>`.
The key is the one the cinema's own Eventive site ships to every browser (its tenant bundle,
`<script data-type="tenant" src=…>`, contains "event_bucket" and "api_key"). It is used only when it
appears on the cinema's public pages; nothing is guessed, and the README says so. Virtual and undated
events are skipped; start_time is UTC and each event names its own time zone.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

from ..base import BaseScraper
from ..models import RawPage, Screening
from ..normalize import clean_text, iso, language_from_text, make_id, normalize_format, to_local
from . import Candidate, register_adapter

API = "https://api.eventive.org/event_buckets/{bucket}/events"
BUCKET = re.compile(r'"event_bucket"\s*:\s*"([0-9a-f]{24})"')
KEY = re.compile(r'"api_key"\s*:\s*"([0-9a-f]{32})"')
SITE = re.compile(r"https?://([a-z0-9-]+)\.eventive\.org", re.I)


def _int(v) -> int | None:
    m = re.match(r"\s*(\d+)", str(v or ""))
    return int(m.group(1)) if m else None


@register_adapter("eventive")
class EventiveAdapter(BaseScraper):
    PARAMS = {"bucket": str, "api_key": str}
    OPTIONAL_PARAMS = {"site": str}
    DETECT_ORDER = 60

    def fetch(self) -> list[RawPage]:
        return [self.get_page(API.format(bucket=self.params["bucket"]), ext="json",
                              headers={"x-api-key": self.params["api_key"]})]

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        site = self.params.get("site")
        out = []
        for page in pages:
            for ev in json.loads(page.body).get("events") or []:
                if ev.get("is_virtual") or not ev.get("is_dated", True) or ev.get("visibility") == "hidden":
                    continue
                title = clean_text(ev.get("name"))
                try:
                    start = to_local(datetime.fromisoformat(ev["start_time"].replace("Z", "+00:00")),
                                     ev.get("timezone") or self.tz)
                except (KeyError, AttributeError, ValueError):
                    continue
                if not title:
                    continue
                films = ev.get("films") or []
                film = films[0] if len(films) == 1 else {}
                details = film.get("details") or {}
                credits = film.get("credits") or {}
                runtime = _int(details.get("runtime"))
                end = None
                if ev.get("end_time"):
                    try:
                        e = datetime.fromisoformat(ev["end_time"].replace("Z", "+00:00"))
                        end = iso(e, self.tz) if 0 < (e - start).total_seconds() <= 8 * 3600 else None
                    except ValueError:
                        pass
                lang = clean_text(details.get("language"))
                start_s = iso(start, self.tz)
                out.append(Screening(
                    id=make_id(self.venue.id, start_s, title), venue_id=self.venue.id, title=title,
                    start=start_s, day=start_s[:10], end=end,
                    director=clean_text(credits.get("director")), year=_int(details.get("year")),
                    runtime_min=runtime if runtime and runtime <= 600 else None,
                    format=normalize_format(clean_text(details.get("format"))),
                    language=language_from_text(lang) or lang,
                    screen=clean_text((ev.get("venue") or {}).get("name")),
                    note=", ".join(t["name"] for t in ev.get("tags") or [] if t.get("visible") and t.get("name")) or None,
                    detail_url=f"https://{site}.eventive.org/schedule/{ev['id']}" if site and ev.get("id") else None,
                    scraped_at=page.fetched_at))
        return out

    @classmethod
    def detect(cls, probe) -> Candidate | None:
        hosts = []
        if urlparse(probe.url).netloc.lower().endswith(".eventive.org"):
            hosts.append(f"https://{urlparse(probe.url).netloc.lower()}/")
        hosts += [f"https://{m.lower()}.eventive.org/" for m in probe.findall(SITE.pattern)
                  if m.lower() not in ("www", "api", "static", "eventive-static")]
        for home in list(dict.fromkeys(hosts))[:1]:
            r = probe.get(home)
            if not r or r.status != 200:
                continue
            m = re.search(r'<script[^>]+data-type=["\']tenant["\'][^>]+src=["\']([^"\']+)', r.text)
            bundle = probe.get(urljoin(home, m.group(1))) if m else None
            text = bundle.text if bundle and bundle.status == 200 else ""
            b, k = BUCKET.search(text), KEY.search(text)
            if b and k:
                site = urlparse(home).netloc.split(".")[0]
                probe.hints.append("eventive_public_key")
                return Candidate("eventive", {"bucket": b.group(1), "api_key": k.group(1), "site": site},
                                 [f"Eventive site {home}", "event bucket and public API key in its tenant bundle"],
                                 order=cls.DETECT_ORDER)
        return None
