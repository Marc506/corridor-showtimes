"""Filmbot (the "Nightjar" WordPress theme) — showtime listings JSON (PLATFORMS.md §1).

    source: {adapter: filmbot, base_url: https://nitehawkcinema.com/williamsburg}

GET <base_url>/wp-json/nj/v1/showtime/listings
    {"movies": [{movie_id, movie_name, runtime, release_year}], "showtimes": [{movie_id, datetime, purchase_url}]}
`datetime` is venue-local YYYYMMDDHHMMSS without a zone. Multi-branch sites keep the branch in the path.

Some installs only expose the WordPress post type (`/wp-json/nj/v1/showtime`, Vidiots): a list of posts
with `_datetime` (epoch seconds), `_length` (minutes) and a title like "9 to 5 – 10/9/26 @ 4:00 pm".
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from ..base import BaseScraper, ScrapeError
from ..models import RawPage, Screening
from ..normalize import clean_text, end_from_runtime, iso, make_id, to_local
from . import Candidate, register_adapter

LISTINGS = "/wp-json/nj/v1/showtime/listings"
POSTS = "/wp-json/nj/v1/showtime"
POSTS_PER_PAGE = 100
MAX_POST_PAGES = 5
YEAR_SUFFIX = re.compile(r"\s*\((\d{4})\)\s*$")
POST_TITLE = re.compile(r"^(.*?)\s+[–—-]\s+\d{1,2}/\d{1,2}/\d{2,4}\s+@\s+.*$")


def _int(v) -> int | None:
    m = re.match(r"\s*(\d+)", str(v or ""))
    return int(m.group(1)) if m else None


@register_adapter("filmbot")
class FilmbotAdapter(BaseScraper):
    PARAMS = {"base_url": str}
    OPTIONAL_PARAMS = {"endpoint": str}          # "listings" (default) | "posts"
    DETECT_ORDER = 10

    @property
    def base(self) -> str:
        return self.params["base_url"].rstrip("/")

    def fetch(self) -> list[RawPage]:
        if self.params.get("endpoint") != "posts":
            page = self.get_page(self.base + LISTINGS, ext="json")
            if isinstance(_loads(page.body), dict):
                return [page]
            if self.params.get("endpoint") == "listings":
                raise ScrapeError("Filmbot listings endpoint did not return JSON")
        pages = []
        for n in range(1, MAX_POST_PAGES + 1):
            page = self.get_page(self.base + POSTS, ext="json", params={"per_page": POSTS_PER_PAGE, "page": n})
            posts = _loads(page.body)
            if not isinstance(posts, list):
                break
            pages.append(page)
            if len(posts) < POSTS_PER_PAGE:
                break
        if not pages:
            raise ScrapeError("Filmbot endpoints did not return JSON")
        return pages

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        out = []
        for page in pages:
            data = _loads(page.body)
            if isinstance(data, dict):
                out += self._listings(data, page)
            elif isinstance(data, list):
                out += self._posts(data, page)
        return out

    def _row(self, title, start, runtime, year, ticket, detail, note, page) -> Screening:
        start_s = iso(start, self.tz)
        return Screening(
            id=make_id(self.venue.id, start_s, title), venue_id=self.venue.id, title=title,
            start=start_s, day=start.date().isoformat(), end=end_from_runtime(start, runtime),
            year=year, runtime_min=runtime, note=note, detail_url=detail, ticket_url=ticket,
            scraped_at=page.fetched_at)

    def _listings(self, data: dict, page: RawPage) -> list[Screening]:
        movies = {m.get("movie_id"): m for m in data.get("movies") or []}
        out = []
        for st in data.get("showtimes") or []:
            movie = movies.get(st.get("movie_id")) or {}
            title = clean_text(movie.get("movie_name"))
            try:
                start = to_local(datetime.strptime(str(st.get("datetime")), "%Y%m%d%H%M%S"), self.tz)
            except ValueError:
                continue
            if not title:
                continue
            year = _int(movie.get("release_year"))
            if (m := YEAR_SUFFIX.search(title)) and (year is None or int(m.group(1)) == year):
                title, year = title[:m.start()], int(m.group(1))      # "Resident Evil (2026)"
            runtime = _int(movie.get("runtime"))
            runtime = runtime if runtime and 1 <= runtime <= 600 else None
            if year is not None and not 1888 <= year <= 2100:
                year = None
            out.append(self._row(title, start, runtime, year, st.get("purchase_url") or None, None,
                                 clean_text(st.get("qualifier")), page))
        return out

    def _posts(self, posts: list, page: RawPage) -> list[Screening]:
        out = []
        for p in posts:
            raw = clean_text((p.get("title") or {}).get("rendered"))
            ts = str(p.get("_datetime") or "")
            if not raw or not ts.isdigit():
                continue
            m = POST_TITLE.match(raw)
            title = m.group(1) if m else raw
            start = datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(self.tz)
            runtime = _int(p.get("_length"))
            notes = [n for n in ("Sold out" if p.get("_sold_out") else None,
                                 "Open captions" if p.get("_open_captions") else None) if n]
            out.append(self._row(title, start, runtime if runtime and runtime <= 600 else None, None,
                                 p.get("link") or None, None, "; ".join(notes) or None, page))
        return out

    @classmethod
    def detect(cls, probe) -> Candidate | None:
        if not probe.find(r"filmbot|nj/v1"):
            return None
        for root in probe.wp_roots()[:2]:
            base = root[: -len("/wp-json/")] if root.endswith("/wp-json/") else root.rstrip("/")
            r = probe.get(base + LISTINGS)
            if r and r.status == 200 and r.is_json and isinstance(r.json(), dict) and "showtimes" in r.json():
                return Candidate("filmbot", {"base_url": base},
                                 ["page mentions Filmbot", f"{base + LISTINGS} returns showtime JSON "
                                  f"({len(r.json().get('showtimes') or [])} showtimes)"], order=cls.DETECT_ORDER)
            r = probe.get(base + POSTS)
            if r and r.status == 200 and r.is_json and isinstance(r.json(), list):
                return Candidate("filmbot", {"base_url": base, "endpoint": "posts"},
                                 ["page mentions Filmbot", f"{base + POSTS} returns showtime posts"],
                                 order=cls.DETECT_ORDER)
        return None


def _loads(body: str):
    try:
        return json.loads(body)
    except ValueError:
        return None
