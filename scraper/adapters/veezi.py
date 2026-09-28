"""Veezi public ticketing page (PLATFORMS.md §2).

    source: {adapter: veezi, site_token: tt17e5ajy3v48kh5b2kremvnz4, region: uswest}

GET https://ticketing.<region>.veezi.com/sessions/?siteToken=<token> — one server-rendered page, about a
month of sessions. The page carries a JSON-LD list of VisualArtsEvent (full ISO start with offset,
ISO duration, purchase URL), which is what we read. The HTML film blocks add what JSON-LD lacks
(director / year / format from the "2020, 94 min, DCP" description, sold-out sessions) and are the
fallback when a page has no JSON-LD. Veezi's real API needs a token the cinema issues; not used.
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..base import BaseScraper
from ..models import RawPage, Screening
from ..normalize import (clean_text, end_from_runtime, iso, language_from_text, make_id, month_number,
                         nearest_date, normalize_format, smart_title, split_format_suffix, title_norm, to_local)
from . import Candidate, register_adapter
from ._ld import events, fetched_date, to_screening

TOKEN_RE = re.compile(r"ticketing\.(?:(us|uswest|useast|au|nz|uk)\.)?veezi\.com/[^\"'\s<>]*siteToken=([a-z0-9]{26})", re.I)
META_RE = re.compile(r"\b((?:18|19|20)\d{2}),\s*(\d{1,3})\s*min(?:s|utes)?\b[.,]?\s*([^.,\n]*)", re.I)
DATE_RE = re.compile(r"(\d{1,2}),?\s+([A-Za-z]+)")          # "Monday 28, September"


def sessions_url(region: str, token: str) -> str:
    host = f"ticketing.{region}.veezi.com" if region else "ticketing.veezi.com"
    return f"https://{host}/sessions/?siteToken={token}"


def film_blocks(html: str) -> list:
    return BeautifulSoup(html, "lxml").select("#sessionsByFilmConent div.film, #sessionsByFilmContent div.film")


def film_meta(block) -> dict:
    """Director / year / runtime / format / language from a film block's free-text description."""
    title_el = block.select_one("h3.title")
    title = clean_text(title_el.get_text(" ")) if title_el else None
    out = {"title": title, "director": None, "year": None, "runtime_min": None, "format": None, "language": None}
    desc = block.select_one("p.film-desc")
    if not desc:
        return out
    lines = [clean_text(l) for l in desc.get_text("\n").split("\n")]
    lines = [l for l in lines if l]
    text = " ".join(lines)
    if m := META_RE.search(text):
        out["year"], out["runtime_min"] = int(m.group(1)), int(m.group(2))
        fmt = m.group(3).strip()
        out["format"] = normalize_format(fmt) if fmt and len(fmt) <= 20 else None
        # Anthology style: "Director\nTITLE\n2020, 94 min, DCP" — director is the line before the title
        if len(lines) >= 3 and title and title_norm(lines[1]) == title_norm(title) and len(lines[0]) <= 80:
            out["director"] = lines[0]
    out["language"] = language_from_text(text)
    return out


@register_adapter("veezi")
class VeeziAdapter(BaseScraper):
    PARAMS = {"site_token": str}
    OPTIONAL_PARAMS = {"region": str}
    DETECT_ORDER = 20

    def fetch(self) -> list[RawPage]:
        return [self.get_page(sessions_url(self.params.get("region", "us"), self.params["site_token"]))]

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        out = []
        for page in pages:
            blocks = film_blocks(page.body)
            meta = {title_norm(split_format_suffix(m["title"])[0]): m for m in map(film_meta, blocks) if m["title"]}
            sold = {urljoin(page.url, a["href"]) for b in blocks for a in b.select("li.sold-out-session a[href]")}
            rows = [s for o in events(page.body)
                    if (s := to_screening(o, self.venue.id, self.tz, page.url, page.fetched_at, ticket_hint="/purchase/"))]
            if not rows:
                rows = self._from_html(blocks, page)
            for s in rows:
                m = meta.get(title_norm(s.title)) or {}
                for f in ("director", "year", "format", "language"):
                    if getattr(s, f) is None and m.get(f):
                        setattr(s, f, m[f])
                if s.runtime_min is None and m.get("runtime_min"):
                    s.runtime_min = m["runtime_min"]
                if s.ticket_url in sold:
                    s.note = "Sold out"
            out += rows
        return out

    def _from_html(self, blocks, page: RawPage) -> list[Screening]:
        """No JSON-LD: 'Monday 28, September' headings (no year) + '9:15 PM' times."""
        ref = fetched_date(page.fetched_at, self.tz)
        out = []
        for block in blocks:
            m = film_meta(block)
            if not m["title"]:
                continue
            title, fmt = split_format_suffix(m["title"])
            title = smart_title(title)
            for date_el in block.select("h4.date"):
                dm = DATE_RE.search(date_el.get_text(" "))
                mon = month_number(dm.group(2)) if dm else None
                day = nearest_date(mon, int(dm.group(1)), ref) if mon else None
                times = date_el.find_next("ul", class_="session-times")
                if not day or not times:
                    continue
                for li in times.select("li"):
                    try:
                        tm = datetime.strptime(clean_text(li.get_text(" ")).upper().replace(" ", ""), "%I:%M%p").time()
                    except (ValueError, AttributeError):
                        continue
                    start = to_local(datetime.combine(day, tm), self.tz)
                    a = li.select_one("a[href]")
                    start_s = iso(start, self.tz)
                    out.append(Screening(
                        id=make_id(self.venue.id, start_s, title), venue_id=self.venue.id, title=title,
                        start=start_s, day=day.isoformat(), end=end_from_runtime(start, m["runtime_min"]),
                        director=m["director"], year=m["year"], runtime_min=m["runtime_min"],
                        format=fmt or m["format"], language=m["language"],
                        note="Sold out" if "sold-out-session" in (li.get("class") or []) else None,
                        ticket_url=a["href"] if a else None, scraped_at=page.fetched_at))
        return out

    @classmethod
    def detect(cls, probe) -> Candidate | None:
        found = probe.findall(TOKEN_RE.pattern)
        if not found:
            return None
        region, token = found[0]
        return Candidate("veezi", {"site_token": token.lower(), "region": (region or "us").lower()},
                         [f"Veezi ticketing link with siteToken={token.lower()}"], order=cls.DETECT_ORDER)
