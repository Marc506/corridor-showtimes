"""Paris Theater (NYC) — screenslate for the schedule, plus the special events on the theatre's own site
(SOURCES.md §16).

    source: {adapter: custom, module: paris, nid: 43542}

The showtimes live only on the ticketing site (tickets.paristheaternyc.com), which answers programs with a
Cloudflare block — not worked around. screenslate lists the schedule a few days ahead. The theatre's home page
(Next.js) embeds its special events weeks ahead in the page's RSC payload (`self.__next_f.push([1,"…"])`):

    {"id":137,"attributes":{"EventName":"LA BOLA NEGRA | Sneak Preview + Q&A with …","EventDate":"2026-10-15",
     "TicketLink":"https://tickets.paristheaternyc.com/order/showtimes/2001-3093/seats","EventTime":"7:05 PM",…}}

Event names are in capitals and carry no year ("A PLACE IN THE SUN | Introduced by Karina Longworth"); the
same payload has the film records ({"FilmName":"A Place in the Sun","Slug":"a-place-in-the-sun-paris",
"Director":"George Stevens",…,"Year":"1951"}), which give the title as written, director, year and film page —
without them TMDB would pick a 2024 namesake. An event that screenslate also lists (same start within 10
minutes, same film) adds its note and ticket link to that showing; the others are added. All rows count as this
venue's primary data.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from ..adapters.screenslate import ScreenslateScraper
from ..models import RawPage, Screening
from ..normalize import clean_text, iso, make_id, parse_iso, smart_title, title_norm, to_local
from ..registry import register

HOME = "https://www.paristheaternyc.com/"
EVENT = re.compile(r'\{"id":(\d+),"attributes":\{"EventName":"((?:[^"\\]|\\.)*)","EventDate":"(\d{4}-\d{2}-\d{2})"'
                   r'(?:(?!"attributes").)*?"TicketLink":"([^"]*)"(?:(?!"attributes").)*?"EventTime":"([^"]*)"', re.S)
TIME = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*([AP]M)$", re.I)
FILM = re.compile(r'"FilmName":"((?:[^"\\]|\\.)*)","Slug":"([^"]*)"')


def rsc_text(html: str) -> str:
    """The Next.js RSC payload of a page, decoded from its self.__next_f.push([1,"…"]) string chunks."""
    out = []
    for chunk in re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', html):
        try:
            out.append(json.loads(f'"{chunk}"'))
        except ValueError:
            continue
    return "".join(out)


def parse_films(text: str) -> dict[str, dict]:
    """title_norm(film name) -> {title, director, year, url} from the film records in the RSC payload."""
    films = {}
    starts = list(FILM.finditer(text))
    for i, m in enumerate(starts):
        seg = text[m.end(): starts[i + 1].start() if i + 1 < len(starts) else m.end() + 4000]
        name = clean_text(json.loads(f'"{m.group(1)}"'))
        director = re.search(r'"Director":"((?:[^"\\]|\\.)*)"', seg)
        year = re.search(r'"Year":"((?:18|19|20)\d{2})"', seg)
        films.setdefault(title_norm(name), {
            "title": name, "url": f"{HOME}film/{m.group(2)}" if m.group(2) else None,
            "director": clean_text(json.loads(f'"{director.group(1)}"')) if director else None,
            "year": int(year.group(1)) if year else None})
    return films


def parse_events(html: str) -> list[dict]:
    """[{title, note, date, hour, minute, ticket_url, director, year, detail_url}] for the special events on
    the home page, completed from the film records."""
    text = rsc_text(html)
    films = parse_films(text)
    events = {}
    for m in EVENT.finditer(text):
        name = json.loads(f'"{m.group(2)}"')
        t = TIME.match(m.group(5).strip())
        if not t:
            continue
        h, mi = int(t.group(1)) % 12 + (12 if t.group(3).upper() == "PM" else 0), int(t.group(2) or 0)
        title, _, note = (clean_text(x) for x in name.partition("|"))
        film = films.get(title_norm(title), {})
        events[m.group(1)] = {"title": film.get("title") or smart_title(title), "note": note or None,
                              "date": m.group(3), "hour": h, "minute": mi, "ticket_url": m.group(4) or None,
                              "director": film.get("director"), "year": film.get("year"),
                              "detail_url": film.get("url") or HOME}
    return list(events.values())


def same_film(a: str, b: str) -> bool:
    x, y = title_norm(a), title_norm(b)
    return bool(x and y) and (x == y or x.startswith(y) or y.startswith(x))


@register("paris")
class ParisScraper(ScreenslateScraper):
    source = "primary"

    def fetch(self) -> list[RawPage]:
        return super().fetch() + [self.get_page(HOME)]

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        home = [p for p in pages if p.url.startswith(HOME)]
        rows = super().parse([p for p in pages if not p.url.startswith(HOME)])
        for r in rows:
            r.source = "primary"
        for page in home:
            for e in parse_events(page.body):
                d = datetime.fromisoformat(e["date"])
                start = to_local(d.replace(hour=e["hour"], minute=e["minute"]), self.tz)
                twin = next((r for r in rows if abs(parse_iso(r.start, self.tz) - start) <= timedelta(minutes=10)
                             and same_film(r.title, e["title"])), None)
                if twin:
                    twin.note = twin.note or e["note"]
                    twin.ticket_url = e["ticket_url"] or twin.ticket_url
                    continue
                start_s = iso(start, self.tz)
                rows.append(Screening(
                    id=make_id(self.venue.id, start_s, e["title"]), venue_id=self.venue.id, title=e["title"],
                    start=start_s, day=start_s[:10], note=e["note"], detail_url=e["detail_url"],
                    director=e["director"], year=e["year"],
                    ticket_url=e["ticket_url"], scraped_at=page.fetched_at))
        return rows
