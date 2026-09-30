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
# NYFF's outer-borough screenings are separate entries named "<film> <place>" ("Bucking Fastard Bronx")
PLACES = ("Bronx", "Brooklyn", "Queens", "Staten Island", "Harlem", "Manhattan")


def split_place(title: str, all_titles: set[str]) -> tuple[str, str | None]:
    """'Bucking Fastard Bronx' -> ('Bucking Fastard', 'Bronx'): the place is where it screens, not part of
    the title. Stripped when the rest is another film in the same feed, or when it's a borough name."""
    for base in sorted(all_titles, key=len, reverse=True):
        if base != title and title.startswith(base + " "):
            rest = title[len(base):].strip()
            if 1 <= len(rest.split()) <= 3:
                return base, rest
    for place in PLACES:
        if title.endswith(" " + place) and len(title) > len(place) + 3:
            return title[: -len(place) - 1].strip(), place
    return title, None


@register("filmlinc")
class FilmLincScraper(BaseScraper):
    def fetch(self) -> list[RawPage]:
        return [self.get_page(API, ext="json")]

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        out = []
        for page in pages:
            films = json.loads(page.body).get("films", [])
            titles = {t for t in (clean_text(f.get("title")) for f in films) if t}
            series_of = {}                                   # a film's festival, for its borough editions
            for f in films:
                for st in f.get("showtimes") or []:
                    sr = PRESALE_SERIES.get((st.get("presaleSchedule") or {}).get("presaleType"))
                    if sr:
                        series_of.setdefault(clean_text(f.get("title")), sr)
            for film in films:
                title = clean_text(film.get("title"))
                if not title or NON_SCREENING.search(title):
                    continue
                title, place = split_place(title, titles)
                slug = film.get("slug")
                for st in film.get("showtimes") or []:
                    if not st.get("dateTimeET"):
                        continue
                    start = parse_iso(st["dateTimeET"], self.tz)
                    start_s = iso(start, self.tz)
                    notes = [place] if place else []
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
                        series=PRESALE_SERIES.get((st.get("presaleSchedule") or {}).get("presaleType"))
                        or series_of.get(title),
                        screen=clean_text(st.get("venue")),
                        note="; ".join(notes) or None,
                        detail_url=f"https://www.filmlinc.org/films/{slug}/" if slug else None,
                        ticket_url=st.get("ticketsUrl") or None,
                        scraped_at=page.fetched_at,
                    ))
        return out
