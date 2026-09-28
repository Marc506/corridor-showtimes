"""Film at Lincoln Center — unofficial open API behind their site (SOURCES.md §2)."""
from __future__ import annotations

import json
import re

from ..base import BaseScraper
from ..models import RawPage, Screening
from ..normalize import clean_text, iso, make_id, parse_iso
from ..registry import register

API = "https://api.filmlinc.org/showtimes"
NON_SCREENING = re.compile(r"\b(pass(es)?|vouchers?|memberships?|packages?)\b", re.I)
PRESALE_SERIES = {"nyff": "New York Film Festival", "met-guild": "Met Opera Live in HD"}


@register("filmlinc")
class FilmLincScraper(BaseScraper):
    def fetch(self) -> list[RawPage]:
        return [self.get_page(API, ext="json")]

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        out = []
        for page in pages:
            for film in json.loads(page.body).get("films", []):
                title = clean_text(film.get("title"))
                if not title or NON_SCREENING.search(title):
                    continue
                slug = film.get("slug")
                for st in film.get("showtimes") or []:
                    if not st.get("dateTimeET"):
                        continue
                    start = parse_iso(st["dateTimeET"])
                    start_s = iso(start)
                    notes = []
                    if st.get("specialEvent"):
                        notes.append("Special event")
                    if st.get("freeEvent"):
                        notes.append("Free")
                    if st.get("openCaptions"):
                        notes.append("Open captions")
                    out.append(Screening(
                        id=make_id(self.venue.id, start_s, title),
                        venue_id=self.venue.id,
                        title=title,
                        start=start_s,
                        day=start.date().isoformat(),
                        series=PRESALE_SERIES.get((st.get("presaleSchedule") or {}).get("presaleType")),
                        screen=clean_text(st.get("venue")),
                        note="; ".join(notes) or None,
                        detail_url=f"https://www.filmlinc.org/films/{slug}/" if slug else None,
                        ticket_url=st.get("ticketsUrl") or None,
                        scraped_at=page.fetched_at,
                    ))
        return out
