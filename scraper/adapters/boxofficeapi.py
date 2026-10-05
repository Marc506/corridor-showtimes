"""Webedia Movies Pro cinema sites — Landmark Theatres and other chains on its Gatsby platform
(PLATFORMS.md §13).

    source: {adapter: boxofficeapi, site: "https://www.landmarktheatres.com", theater: X081D}

The pages render showtimes in the browser from the site's own JSON endpoints, which a plain GET reads:

  <site>/api/gatsby-source-boxofficeapi/schedule?theaters={"id":"X081D","timeZone":"America/New_York"}
        &from=<local start>&to=<local end>&includeAllMovies=true
      -> {"X081D": {"schedule": {<movieId>: {<YYYY-MM-DD>: [{startsAt, tags, screen, data.ticketing}]}}}}
      one request covers the whole horizon
  <site>/api/gatsby-source-boxofficeapi/movies?basic=false&castingLimit=3&ids=<id>&ids=<id>…
      -> titles, directors, release date, runtime in *seconds*; batched 40 ids per request

A chain's site lists every location (Landmark has ~26 across the US); `theater` keeps one. The id is the
first part of the theater page's path: /theaters/x081d-landmark-ritz-five-philadelphia/ -> X081D.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from urllib.parse import urlencode, urlparse

from ..base import BaseScraper
from ..models import RawPage, Screening
from ..normalize import clean_text, end_from_runtime, iso, make_id, to_local, today_local
from . import Candidate, register_adapter

API = "/api/gatsby-source-boxofficeapi"
MAX_DAYS = 60
BATCH = 40
FILM = {"35mm": "35mm", "70mm": "70mm", "16mm": "16mm"}
NOTES = {"Showtime.Accessibility.Subtitled": "Subtitled", "Showtime.Accessibility.OpenCaption": "Open captions",
         "Showtime.Accessibility.OpenCaptions": "Open captions"}
THEATER_PATH = re.compile(r"/theaters/([a-z0-9]{5})-", re.I)


def slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def person(node: dict) -> str | None:
    p = (node or {}).get("person") or {}
    return clean_text(" ".join(x for x in (p.get("firstName"), p.get("lastName")) if x))


def movie_facts(m: dict) -> dict:
    """Title (minus a trailing '(1932)' that just repeats the year), directors, year, runtime in minutes."""
    title = clean_text(m.get("title") or (m.get("locale") or {}).get("title")) or ""
    year = None
    if rel := (m.get("release") or "")[:4]:
        year = int(rel) if rel.isdigit() else None
    if year and title.endswith(f"({year})"):
        title = title[: -len(f"({year})")].strip()
    nodes = ((m.get("directors") or {}).get("nodes") or []) + ((m.get("coDirectors") or {}).get("nodes") or [])
    directors = list(dict.fromkeys(n for n in (person(x) for x in nodes) if n))
    secs = m.get("runtime")
    runtime = round(secs / 60) if isinstance(secs, (int, float)) and 60 <= secs <= 6 * 3600 else None
    return {"title": title, "director": ", ".join(directors[:3]) or None, "year": year, "runtime": runtime}


@register_adapter("boxofficeapi")
class BoxOfficeApiAdapter(BaseScraper):
    PARAMS = {"site": str, "theater": str}
    DETECT_ORDER = 16
    enforce_budget = True                     # 1 schedule + a few movie batches

    def _base(self) -> str:
        return self.params["site"].rstrip("/") + API

    def fetch(self) -> list[RawPage]:
        theater = str(self.params["theater"]).upper()
        start = today_local(self.tz)
        end = start + timedelta(days=min(self.venue.horizon_days, MAX_DAYS))
        q = urlencode({"theaters": json.dumps({"id": theater, "timeZone": str(self.tz)}, separators=(",", ":")),
                       "from": f"{start.isoformat()}T03:00:00", "to": f"{end.isoformat()}T03:00:00",
                       "includeAllMovies": "true"})
        sched = self.get_page(f"{self._base()}/schedule?{q}", ext="json")
        pages = [sched]
        ids = list((json.loads(sched.body or "{}").get(theater) or {}).get("schedule") or {})
        for i in range(0, len(ids), BATCH):
            q = urlencode([("basic", "false"), ("castingLimit", "3")] + [("ids", x) for x in ids[i:i + BATCH]])
            pages.append(self.get_page(f"{self._base()}/movies?{q}", ext="json"))
        return pages

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        theater = str(self.params["theater"]).upper()
        site = self.params["site"].rstrip("/")
        movies, sched, fetched = {}, {}, ""
        for p in pages:
            data = json.loads(p.body or "null")
            if "/schedule?" in p.url and isinstance(data, dict):
                sched = (data.get(theater) or {}).get("schedule") or {}
                fetched = p.fetched_at
            elif isinstance(data, list):
                movies.update({str(m.get("id")): m for m in data if isinstance(m, dict)})
        out = []
        for movie_id, days in sched.items():
            m = movies.get(str(movie_id)) or {}
            f = movie_facts(m)
            if not f["title"]:
                continue
            for showings in days.values():
                for s in showings or []:
                    try:
                        start = to_local(datetime.fromisoformat(s["startsAt"]), self.tz)
                    except (KeyError, TypeError, ValueError):
                        continue
                    tags = s.get("tags") or []
                    fmt = next((FILM[t.rsplit(".", 1)[-1].lower()] for t in tags
                                if t.startswith("Format.Projection.") and t.rsplit(".", 1)[-1].lower() in FILM), None)
                    if not fmt and "Format.Projection.Digital" in tags:
                        fmt = "DCP"
                    notes = list(dict.fromkeys(NOTES[t] for t in tags if t in NOTES))
                    tickets = (s.get("data") or {}).get("ticketing") or []
                    ticket = next((u for t in tickets if t.get("provider") == "default" for u in t.get("urls") or []), None)
                    screen = ((s.get("screen") or {}).get("name") or "").strip()
                    start_s = iso(start, self.tz)
                    out.append(Screening(
                        id=make_id(self.venue.id, start_s, f["title"]), venue_id=self.venue.id, title=f["title"],
                        start=start_s, day=start.date().isoformat(), end=end_from_runtime(start, f["runtime"]),
                        director=f["director"], year=f["year"], runtime_min=f["runtime"], format=fmt,
                        screen=f"Screen {screen}" if screen.isdigit() else (screen or None),
                        note="; ".join(notes) or None,
                        detail_url=f"{site}/movies/{movie_id}-{slug(clean_text(m.get('title')) or f['title'])}/",
                        ticket_url=ticket, scraped_at=fetched))
        return out

    @classmethod
    def detect(cls, probe) -> Candidate | None:
        """A Webedia site's theater page: /theaters/<id>-<name>/ with a working scheduledMovies endpoint."""
        u = urlparse(probe.url)
        m = THEATER_PATH.search(u.path)
        site = f"{u.scheme}://{u.netloc}"
        if not m:
            html = " ".join(r.text or "" for r in getattr(probe, "pages", []) or [])
            if "webediamovies" in html or "gatsby-source-boxofficeapi" in html:
                probe.hints.append("boxofficeapi_need_theater")   # a chain page: ask for one theater's page
            return None
        theater = m.group(1).upper()
        r = probe.get(f"{site}{API}/scheduledMovies?theaterId={theater}")
        try:
            data = json.loads(r.text) if r and r.status == 200 else None
        except ValueError:
            data = None
        if not isinstance(data, dict) or "scheduledDays" not in data:
            return None
        n = len(data.get("scheduledDays") or {})
        return Candidate("boxofficeapi", {"site": site, "theater": theater},
                         [f"Webedia box-office API for theater {theater} ({n} films scheduled)"], order=cls.DETECT_ORDER)
