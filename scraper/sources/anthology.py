"""Anthology Film Archives — server-rendered list view, one page per month (SOURCES.md §4)."""
from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

from ..base import BaseScraper
from ..models import RawPage, Screening
from ..normalize import (clean_text, end_from_runtime, iso, language_from_text, make_id, normalize_format,
                         smart_title, to_local, today_local)
from ..registry import register

BASE = "https://www.anthologyfilmarchives.org"
LIST = BASE + "/film_screenings/calendar"
MONTHS_AHEAD = 3

# "[Country, ][In X with English subtitles, ]1984, 91 min, 16mm-to-DCP[, silent | . Notes]"
META_RE = re.compile(r"(?:^|,\s*)(\d{4}),\s*(\d+)\s*min\b[.,]?\s*(.*)$")


def parse_meta(line: str) -> tuple[int | None, int | None, str | None]:
    m = META_RE.search(line)
    if not m:
        return None, None, None
    fmt = re.split(r"[,.]\s", m.group(3).strip() + " ", maxsplit=1)[0].strip(" .,") or None
    return int(m.group(1)), int(m.group(2)), normalize_format(fmt)


@register("anthology")
class AnthologyScraper(BaseScraper):
    def fetch(self) -> list[RawPage]:
        pages = []
        today = today_local(self.tz)
        y, m = today.year, today.month
        for _ in range(MONTHS_AHEAD):
            page = self.get_page(LIST, params={"view": "list", "month": m, "year": y})
            pages.append(page)
            if not BeautifulSoup(page.body, "lxml").select_one("div.film-showing"):
                break                   # schedule not published this far out yet
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return pages

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        out = []
        for page in pages:
            qs = parse_qs(urlparse(page.url).query)
            year, month = int(qs["year"][0]), int(qs["month"][0])
            soup = BeautifulSoup(page.body, "lxml")
            day: date | None = None
            for node in soup.select("h3.current-day, div.film-showing"):
                if "current-day" in (node.get("class") or []):
                    m = re.search(r"\b(\d{1,2})\b", node.get_text(" "))
                    day = date(year, month, int(m.group(1))) if m else None
                elif day:
                    out.extend(self._parse_showing(node, day, page))
        return out

    def _parse_showing(self, node: Tag, day: date, page: RawPage) -> list[Screening]:
        det = node.select_one(".showing-details") or node
        title_el = det.select_one("span.film-title")
        title = smart_title(clean_text(title_el.get_text(" "))) if title_el else None
        if not title:
            return []

        director = year = runtime = fmt = language = None
        # bare text nodes after the title: "by X" and "1975, 167 min, 16mm-to-DCP"
        for sib in title_el.next_siblings:
            if isinstance(sib, Tag) and sib.name not in ("br",):
                break
            if isinstance(sib, NavigableString):
                line = clean_text(str(sib))
                if not line:
                    continue
                if line.startswith("by "):
                    director = line[3:].strip()
                elif year is None:
                    year, runtime, fmt = parse_meta(line)
                    language = language_from_text(line)

        series_el = det.select_one("p.series-note")
        series = None
        if series_el:
            series = clean_text(series_el.get_text(" ").replace("This screening is part of:", ""))
            series = smart_title(series)
        ticket = det.select_one('.film-notes a[href*="veezi"], a[href*="ticketing"]')

        rows = []
        for a in det.select('a[name^="showing-"]'):
            t = clean_text(a.get_text(" ")).rstrip(",").strip()
            try:
                tm = datetime.strptime(t, "%I:%M %p").time()
            except ValueError:
                continue
            start = to_local(datetime.combine(day, tm), self.tz)
            start_s = iso(start, self.tz)
            anchor = a["name"]
            rows.append(Screening(
                id=make_id(self.venue.id, start_s, title),
                venue_id=self.venue.id, title=title, start=start_s, day=day.isoformat(),
                end=end_from_runtime(start, runtime),
                director=director, year=year, runtime_min=runtime, format=fmt, language=language, series=series,
                detail_url=f"{LIST}?view=list&month={day.month}&year={day.year}#{anchor}",
                ticket_url=ticket["href"] if ticket else None,
                scraped_at=page.fetched_at,
            ))
        return rows
