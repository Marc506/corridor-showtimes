"""Metrograph — /nyc/ lists ~4 weeks on one page. The origin rate-limits by IP (SOURCES.md §6):
exactly ONE GET per run, no query params, no detail pages, 429 = stop (BaseScraper does that)."""
from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from ..base import BaseScraper
from ..models import RawPage, Screening
from ..normalize import clean_text, end_from_runtime, iso, make_id, normalize_format, to_local
from ..registry import register

URL = "https://metrograph.com/nyc/"
SITE = "https://metrograph.com"
KNOWN_FORMATS = {"dcp", "4k dcp", "35mm", "16mm", "70mm", "digital", "digital video", "vhs",
                 "blu-ray", "super 8", "8mm", "2k dcp"}


def parse_metadata(text: str | None) -> dict:
    """'Wong Kar-wai / 1997 / 96min / DCP' — fields may be missing, so classify each part."""
    out: dict = {"director": None, "year": None, "runtime_min": None, "format": None}
    if not text:
        return out
    rest = []
    for part in (clean_text(p) for p in text.split("/")):
        if not part:
            continue
        if re.fullmatch(r"(18|19|20)\d{2}", part):
            out["year"] = int(part)
        elif m := re.fullmatch(r"(\d+)\s*min", part, re.I):
            out["runtime_min"] = int(m.group(1))
        elif part.lower() in KNOWN_FORMATS:
            out["format"] = normalize_format(part)
        else:
            rest.append(part)
    out["director"] = ", ".join(rest) or None
    return out


@register("metrograph")
class MetrographScraper(BaseScraper):
    def fetch(self) -> list[RawPage]:
        return [self.get_page(URL)]

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        out = []
        for page in pages:
            soup = BeautifulSoup(page.body, "lxml")
            for day_div in soup.select("div.calendar-list-day"):
                m = re.fullmatch(r"calendar-list-day-(\d{4}-\d{2}-\d{2})", day_div.get("id", ""))
                if not m:
                    continue                    # e.g. calendar-list-day-none
                day = date.fromisoformat(m.group(1))
                for item in day_div.select("div.item"):
                    a = item.select_one("h4 a.title") or item.select_one("h4 a")
                    title = clean_text(a.get_text(" ")) if a else None
                    if not title:
                        continue
                    meta_el = item.select_one("div.film-metadata")
                    meta = parse_metadata(meta_el.get_text(" ") if meta_el else None)
                    desc_el = item.select_one("div.film-description")
                    desc = clean_text(desc_el.get_text(" ")) if desc_el else None
                    detail = urljoin(SITE, a["href"]) if a.get("href") else None
                    for t in item.select("div.showtimes a"):
                        label = clean_text(t.get_text())
                        try:
                            tm = datetime.strptime(label.replace(" ", "").upper(), "%I:%M%p").time()
                        except (ValueError, AttributeError):
                            continue
                        start = to_local(datetime.combine(day, tm))
                        start_s = iso(start)
                        out.append(Screening(
                            id=make_id(self.venue.id, start_s, title),
                            venue_id=self.venue.id, title=title, start=start_s, day=day.isoformat(),
                            end=end_from_runtime(start, meta["runtime_min"]),
                            director=meta["director"], year=meta["year"],
                            runtime_min=meta["runtime_min"], format=meta["format"],
                            note="; ".join(x for x in (_note_for_day(desc, day), _sold_out(t)) if x) or None,
                            detail_url=detail, ticket_url=t.get("href") or None,
                            scraped_at=page.fetched_at,
                        ))
        return out


_MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july",
                                       "august", "september", "october", "november", "december"], 1)}
_DATED = re.compile(r"\bon (?:\w+day,\s*)?([A-Z][a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?\b")


def _note_for_day(desc: str | None, day: date) -> str | None:
    """Descriptions are per film; 'Q&A … on Saturday, September 26th' belongs to that day only."""
    if not desc:
        return None
    m = _DATED.search(desc)
    if m and m.group(1).lower() in _MONTHS:
        if (_MONTHS[m.group(1).lower()], int(m.group(2))) != (day.month, day.day):
            return None
        return desc[:m.start()].strip() or desc
    return desc


def _sold_out(a) -> str | None:
    cls = " ".join(a.get("class") or [])
    return "Sold out" if "sold" in cls.lower() or "sold out" in (a.get("title") or "").lower() else None
