"""The Secret Cinema (Philadelphia) — a floating 16mm repertory series; its hand-written home page (SOURCES.md §18).

    source: {adapter: custom, module: secret_cinema}

The page (UTF-16, no charset header) announces the next programmes one per section between <HR> rules:

    <H2><B><I>Archive Discoveries 2026:</B></H2>
    <H2><B>Unseen Curiosities from the Secret Cinema Collection </I>at Rotunda</B></H2>
    <P><B>Thursday, October 8, 2026<BR>8:00 pm<BR>Admission: FREE</B>
    <P><B><A HREF="https://www.therotunda.org">The Rotunda</A><BR>4014 Walnut Street<BR>Philadelphia</B>
    …<P><B><I>Invisible Walls </I>(1968, Dir: Richard A. Cowan) - </B>The "invisible walls" of the title …

A section with a date and a time is one screening: title from its headings (without the trailing "at <place>"),
the place's name as the screen, "7:30 pm until 11:30 pm" as start and end, and the films it highlights in the
note. "FUTURE SECRET CINEMA EVENTS (more info soon)" lists dates without times — left out until announced.
"""
from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup

from ..base import BaseScraper
from ..models import RawPage, Screening
from ..normalize import clean_text, iso, make_id, title_norm, to_local
from ..registry import register

HOME = "https://www.thesecretcinema.com/"
DATE = re.compile(r"\b(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day,\s+([A-Z][a-z]+ \d{1,2}, \d{4})")
CLOCK = r"(\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?)"
TIME = re.compile(CLOCK + r"(?:\s+(?:until|to|-|–)\s+" + CLOCK + r")?", re.I)
FILM = re.compile(r"^(.+?)\s*\(((?:18|19|20)\d{2}s?),\s*Dir(?:\.|:)?\s*([^)]+)\)", re.I)


def at_time(day: str, clock: str, tz) -> datetime:
    """'October 8, 2026' + '8:00 pm' / '8 pm' -> aware local datetime."""
    c = re.sub(r"[.\s]", "", clock).upper()
    fmt = "%B %d, %Y %I:%M%p" if ":" in c else "%B %d, %Y %I%p"
    return to_local(datetime.strptime(f"{day} {c}", fmt), tz)


def sections(html: str) -> list[BeautifulSoup]:
    return [BeautifulSoup(part, "lxml") for part in re.split(r"<hr\b[^>]*>", html, flags=re.I)]


@register("secret_cinema")
class SecretCinemaScraper(BaseScraper):
    def fetch(self) -> list[RawPage]:
        return [self.get_page(HOME)]

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        out = []
        for page in pages:
            for sec in sections(page.body):
                if s := self.screening(sec, page):
                    out.append(s)
        return out

    def screening(self, sec: BeautifulSoup, page: RawPage) -> Screening | None:
        heads = [clean_text(h.get_text(" ")) for h in sec.find_all("h2")]
        when = next((b for b in sec.find_all("b") if DATE.search(b.get_text(" "))), None)
        if not heads or when is None:
            return None
        lines = [clean_text(x) for x in when.get_text("\n").split("\n") if clean_text(x)]
        day = DATE.search(lines[0]).group(1)
        times = next((m for line in lines[1:] if (m := TIME.fullmatch(line))), None)
        if times is None:
            return None
        start = at_time(day, times.group(1), self.tz)
        end = at_time(day, times.group(2), self.tz) if times.group(2) else None

        # the place: the bold block right after the date (its first line, often a link)
        place_b = when.find_next("b")
        place = clean_text(place_b.get_text("\n").split("\n")[0]) if place_b else None
        title = clean_text(" ".join(h for h in heads if h))
        if place and (m := re.search(r"\s+at\s+(?:the\s+)?([^:]+)$", title, re.I)) \
                and title_norm(m.group(1)) in title_norm(place):
            title = title[: m.start()]
        title = title.rstrip(" :")

        films = []
        for b in sec.find_all("b"):
            if b.find("i") and (m := FILM.match(clean_text(b.get_text(" ")) or "")):
                films.append(f"{clean_text(m.group(1))} ({m.group(2)}, dir. {clean_text(m.group(3))})")
        admission = next((line.split(":", 1)[1].strip() for line in lines if line.lower().startswith("admission:")), "")
        notes = (["Free"] if admission.lower() == "free" else []) + (["; ".join(films)] if films else [])
        text = sec.get_text(" ")
        start_s = iso(start, self.tz)
        return Screening(
            id=make_id(self.venue.id, start_s, title), venue_id=self.venue.id, title=title, start=start_s,
            day=start.date().isoformat(), end=iso(end, self.tz) if end and end > start else None,
            format="16mm" if re.search(r"\b16\s*mm\b", text) else "Film",   # never video: always film
            screen=place, note="; ".join(n for n in notes if n) or None, detail_url=HOME, scraped_at=page.fetched_at)
