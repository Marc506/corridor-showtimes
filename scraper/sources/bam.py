"""BAM Rose Cinemas — open JSON calendar API (SOURCES.md §1)."""
from __future__ import annotations

import json
import re
from datetime import timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..base import BaseScraper
from ..models import RawPage, Screening
from ..normalize import clean_text, iso, language_from_text, make_id, normalize_format, parse_iso, today_local
from ..registry import register

API = "https://www.bam.org/api/BAMApi/GetCalendarEventsByDayWithOnGoing"
SITE = "https://www.bam.org"


def _us_date(d) -> str:
    return f"{d.month}/{d.day}/{d.year}"      # M/D/YYYY, no zero padding


def parse_detail(html: str) -> dict:
    """Film page: 'Directed by Matt Johnson\n(2026)', 'Part of\nX', 'RUNNING TIME\n106min', 'FORMAT\nDCP'."""
    text = BeautifulSoup(html, "lxml").get_text("\n", strip=True)
    out: dict = {}
    if m := re.search(r"Directed by ([^\n]+)(?:\n\((\d{4})\))?", text):
        out["director"] = clean_text(m.group(1))
        if m.group(2):
            out["year"] = int(m.group(2))
    if m := re.search(r"RUNNING TIME\n(\d+)\s*min", text, re.I):
        out["runtime_min"] = int(m.group(1))
    if m := re.search(r"\nFORMAT\n([^\n]+)", text):
        out["format"] = normalize_format(m.group(1))
    if m := re.search(r"\nLANGUAGE\n([^\n]+)", text):
        lang = language_from_text(m.group(1))
        out["language"] = lang or ("English" if m.group(1).strip().lower() in ("english", "in english") else None)
    if m := re.search(r"\nPart of\n([^\n]+)", text):
        series = clean_text(m.group(1))
        if series and not re.fullmatch(r"BAM Film( \d{4})?", series):
            out["series"] = series
    return out


@register("bam")
class BamScraper(BaseScraper):
    def fetch(self) -> list[RawPage]:
        start = today_local(self.tz)
        end = start + timedelta(days=self.venue.horizon_days)
        return [self.get_page(API, ext="json", params={"start": _us_date(start), "end": _us_date(end)})]

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        out = []
        for page in pages:
            for ev in json.loads(page.body):
                genres = [g.strip() for g in (ev.get("genres") or "").split(",")]
                if "Film" not in genres:
                    continue
                title = clean_text(ev.get("name"))
                if not title:
                    continue
                other = [g for g in genres if g and g != "Film"]
                more = ev.get("moreLink")
                for perf in ev.get("performances") or []:
                    start = parse_iso(perf, self.tz)
                    start_s = iso(start, self.tz)
                    out.append(Screening(
                        id=make_id(self.venue.id, start_s, title),
                        venue_id=self.venue.id,
                        title=title,
                        start=start_s,
                        day=start.date().isoformat(),
                        note=", ".join(other) or None,
                        detail_url=SITE + more if more and more.startswith("/") else more,
                        ticket_url=urljoin(SITE, ev["buyLink"]) if ev.get("buyLink") else None,
                        scraped_at=page.fetched_at,
                    ))
        return out

    def enrich(self, screenings: list[Screening]) -> None:
        self.enrich_by_url(screenings, parse_detail,
                           fields=("director", "year", "runtime_min", "format", "series", "language"))
