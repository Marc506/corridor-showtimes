"""L'Alliance New York — event cards + one detail page per card (SOURCES.md §7).

The list page gives titles and detail URLs; each detail page's "Schedule" block has the real
(date, times) pairs. Cards whose schedule is only a date range are series containers ("Jean-Luc
Godard: Unmade and Abandoned"): they have no showings of their own, but their "Events In This Series"
block links to the programmes they contain, which gives each programme its series name.
"""
from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup

from ..base import BaseScraper
from ..models import RawPage, Screening
from ..normalize import clean_text, end_from_runtime, iso, make_id, normalize_format, to_local
from ..registry import register

LIST_URL = "https://lallianceny.org/events/?_event_categories=film"
DATE_RE = re.compile(r"^[A-Z][a-z]+day,\s+([A-Z][a-z]+ \d{1,2}, \d{4})$")
TIME_RE = re.compile(r"^\d{1,2}:\d{2}\s*[AP]M$", re.I)
DIR_LINE = re.compile(r"^Dirs?\.\s+(.*)$", re.I)
# a film credit without a director, e.g. "(1981, 39 min, DCP)" or ", 1982, 11 min, DCP)"
CREDIT = re.compile(r"(?:^|[(,]\s*)((?:18|19|20)\d{2}),\s*(\d+)\s*min\.?(?:,\s*([^()]+?))?\s*\)?\.?$", re.I)


def parse_dir_line(line: str) -> tuple[str, int | None, int | None, str | None] | None:
    """'Dir. Jean Renoir, 1931, 93 min, DCP.' / 'dirs. A and B, France, 2015, DCP' (no regex backtracking)."""
    m = DIR_LINE.match(line.strip())
    if not m:
        return None
    parts = [p.strip(" .") for p in m.group(1).split(",")]
    director, year, runtime, fmt = parts[0], None, None, None
    for p in parts[1:]:
        if re.fullmatch(r"(18|19|20)\d{2}", p):
            year = int(p)
        elif mm := re.fullmatch(r"(\d+)\s*min", p, re.I):
            runtime = int(mm.group(1))
        elif year is not None and fmt is None and p:
            fmt = normalize_format(p)
    return director, year, runtime, fmt


def event_key(url: str) -> str:
    """Normalise an event URL ('/event/x/', 'https://lallianceny.org/event/x') to 'x'."""
    return url.rstrip("/").rsplit("/", 1)[-1].lower()


def series_members(html: str) -> list[str]:
    """Event keys listed under a series page's "Events In This Series" heading (not the site's menus)."""
    soup = BeautifulSoup(html, "lxml")
    heading = soup.find(lambda t: t.name in ("h2", "h3", "h4") and "Events In This Series" in t.get_text(" ", strip=True))
    if not heading:
        return []
    keys = []
    for a in heading.find_all_next("a", href=True):
        if "/event/" in a["href"] and (k := event_key(a["href"])) not in keys:
            keys.append(k)
    return keys


def parse_list(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    cards = []
    for li in soup.select("li.event-card--list"):
        h = li.select_one(".event-card__heading")
        more = li.select_one("a.event-card__learn-more-btn")
        if not h or not more or not more.get("href"):
            continue
        loc = li.select_one(".event-card__location-name")
        cards.append({"title": clean_text(h.get_text(" ")), "url": more["href"],
                      "screen": clean_text(loc.get_text(" ")) if loc else None})
    return cards


def parse_detail(html: str, tz=None) -> dict:
    soup = BeautifulSoup(html, "lxml")
    out: dict = {"showings": [], "director": None, "year": None, "runtime_min": None,
                 "format": None, "series": None, "ticket_url": None, "title": None}

    h1 = soup.select_one("h1.events-heading") or soup.find("h1")
    if h1:
        out["title"] = clean_text(h1.get_text(" "))
        sub = h1.find_next_sibling(class_="brxe-text")
        if sub:
            out["series"] = clean_text(sub.get_text(" "))

    heading = soup.find(lambda t: t.name in ("h2", "h3", "h4") and t.get_text(strip=True) == "Schedule")
    block = heading.find_next(class_="brxe-code") if heading else None
    if block:
        current = None
        for node in block.find_all(["p", "div"]):
            if node.find(["p", "div"]):
                continue                           # only leaf nodes carry text
            text = clean_text(node.get_text(" ")) or ""
            if m := DATE_RE.match(text):
                current = datetime.strptime(m.group(1), "%B %d, %Y").date()
            elif current and TIME_RE.match(text):
                tm = datetime.strptime(text.upper().replace(" ", ""), "%I:%M%p").time()
                out["showings"].append(to_local(datetime.combine(current, tm), tz))

    text = soup.get_text("\n", strip=True)
    films = [f for f in (parse_dir_line(line) for line in text.split("\n")) if f]
    if not films:                                    # programmes that list films as "(1981, 39 min, DCP)"
        for line in text.split("\n"):
            if m := CREDIT.search(line.strip()):
                films.append((None, int(m.group(1)), int(m.group(2)),
                              normalize_format(clean_text(m.group(3))) if m.group(3) else None))
    if films:
        out["director"] = ", ".join(dict.fromkeys(f[0] for f in films if f[0])) or None
        if len(films) == 1:
            out["year"] = films[0][1]
        fmts = {f[3] for f in films if f[3]}
        if len(fmts) == 1:
            out["format"] = fmts.pop()
    if m := re.search(r"Run Time:\s*(\d+)\s*min", text, re.I):
        out["runtime_min"] = int(m.group(1))
    elif len(films) == 1:
        out["runtime_min"] = films[0][2]
    buy = soup.select_one('a[href*="buytickets.at"]')
    out["ticket_url"] = buy["href"] if buy else None
    return out


@register("lalliance")
class LAllianceScraper(BaseScraper):
    def fetch(self) -> list[RawPage]:
        listing = self.get_page(LIST_URL)
        pages = [listing]
        for card in parse_list(listing.body):
            pages.append(self.get_page(card["url"]))
        return pages

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        listing, details = pages[0], {p.url: p for p in pages[1:]}
        cards = parse_list(listing.body)
        # series containers name the programmes they include
        series_of: dict[str, str] = {}
        for card in cards:
            page = details.get(card["url"])
            if page:
                for key in series_members(page.body):
                    series_of.setdefault(key, card["title"])
        out = []
        for card in cards:
            page = details.get(card["url"])
            if not page:
                continue
            d = parse_detail(page.body, self.tz)
            title = card["title"] or d["title"]
            parent = series_of.get(event_key(card["url"]))
            # the programme's own subtitle ("The Remake") becomes a note when the series is known
            series, note = (parent, d["series"]) if parent else (d["series"], None)
            for start in d["showings"]:
                start_s = iso(start, self.tz)
                out.append(Screening(
                    id=make_id(self.venue.id, start_s, title),
                    venue_id=self.venue.id, title=title, start=start_s, day=start.date().isoformat(),
                    end=end_from_runtime(start, d["runtime_min"]),
                    director=d["director"], year=d["year"], runtime_min=d["runtime_min"],
                    format=d["format"], series=series, note=note, screen=card["screen"],
                    detail_url=card["url"], ticket_url=d["ticket_url"],
                    scraped_at=page.fetched_at,
                ))
        return out
