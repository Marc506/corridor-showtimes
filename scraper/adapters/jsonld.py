"""Generic schema.org Event / ScreeningEvent reader (PLATFORMS.md §8).

    source:
      adapter: jsonld
      pages: [https://brattlefilm.org/]                # pages whose JSON-LD lists showtimes
      follow: "a[href*='/movies/']"                     # optional: also read pages linked from them (one hop)
      max_follow: 15
      titles_from_description: true   # optional: films named in quotes in the event's description are the title
      screen_from_location: true      # optional: each event's place is its screen (pop-ups; location.places has addresses)

Only events whose startDate carries a time count — Film Forum's home page lists ScreeningEvents with
empty dates, which must not be mistaken for a schedule. Usually a small site's fallback or a quick
detection signal; a platform adapter is preferred when one matches.
"""
from __future__ import annotations

import re
from dataclasses import replace
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..base import BaseScraper, RequestBudgetExceeded
from ..models import RawPage, Screening
from ..normalize import clean_text, make_id
from . import Candidate, register_adapter
from ._ld import events, to_screening


# 'Young Frankenstein', "They Live", ‘Coraline’ — an apostrophe inside a word ("Schindler's") is not a quote
QUOTED = re.compile(r"(?<![\w'‘“\"])['‘“\"](\S(?:.*?\S)?)['’”\"](?![\w])")


@register_adapter("jsonld")
class JsonLdAdapter(BaseScraper):
    PARAMS = {"pages": list}
    OPTIONAL_PARAMS = {"follow": str, "max_follow": int, "ticket_hint": str, "titles_from_description": bool,
                       "screen_from_location": bool}
    DETECT_ORDER = 80

    def fetch(self) -> list[RawPage]:
        pages = [self.get_page(u) for u in self.params["pages"]]
        sel = self.params.get("follow")
        if sel:
            seen = set(self.params["pages"])
            links = []
            for p in pages:
                for a in BeautifulSoup(p.body, "lxml").select(sel):
                    if a.get("href"):
                        u = urljoin(p.url, a["href"]).split("#")[0]
                        if u not in seen:
                            seen.add(u)
                            links.append(u)
            for u in links[: int(self.params.get("max_follow", 15))]:
                try:
                    pages.append(self.get_page(u))
                except RequestBudgetExceeded:
                    break
        return pages

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        hint = self.params.get("ticket_hint", "/purchase/")
        return [self.adjust(s, o) for p in pages for o in events(p.body)
                if (s := to_screening(o, self.venue.id, self.tz, p.url, p.fetched_at, ticket_hint=hint))]

    def adjust(self, s: Screening, obj: dict) -> Screening:
        """Listing sites name an evening ("Halloween Fest – Friday") and quote its films in the description
        ("Outdoor screenings of 'Young Frankenstein' and 'The Lost Boys' with DJ …"): one or two films become the
        title, three or more keep the event's name; the event's name becomes the series, the description the note."""
        place = obj.get("location") if isinstance(obj.get("location"), dict) else {}
        if self.params.get("screen_from_location") and clean_text(place.get("name")):
            s = replace(s, screen=clean_text(place.get("name")))
        desc = clean_text(obj.get("description") or "")
        films = list(dict.fromkeys(clean_text(m) for m in QUOTED.findall(desc or "")))
        if not self.params.get("titles_from_description") or not films:
            return s
        title = " + ".join(films) if len(films) <= 2 else s.title
        return replace(s, id=make_id(s.venue_id, s.start, title), title=title, series=s.title, note=desc)

    @classmethod
    def detect(cls, probe) -> Candidate | None:
        found = [(r.final_url or r.url, len(events(r.text))) for r in probe.pages]
        found = [(u, n) for u, n in found if n]
        if not found:
            return None
        return Candidate("jsonld", {"pages": [u for u, _ in found]},
                         [f"{n} schema.org events with showtimes on {u}" for u, n in found], order=cls.DETECT_ORDER)
