"""MoMA — Cloudflare managed challenge; needs a real browser (SOURCES.md §8).

Primary path: Playwright opens /calendar/film, collects series links (/calendar/film/<id>),
opens each and parses the '<h3>date</h3> … <li><a href="/calendar/events/<id>">' listing.
If the challenge isn't passed within 30s the run fails and run.py falls back to screenslate
(nid 81), which covers MoMA completely. See `primary_cooldown_h` in venues.yaml.

NOTE: the markup below was taken from SOURCES.md (Wayback 2025-12 snapshot); a live page could
not be captured on 2026-09-24 because Cloudflare escalated the challenge. The first successful
run saves data/raw/<date>/moma*.html — replace tests/fixtures/moma/synthetic_series.html with it.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ..base import BaseScraper, ref_date
from ..models import RawPage, Screening
from ..normalize import clean_text, iso, make_id, to_local
from ..registry import register

SITE = "https://www.moma.org"
START = SITE + "/calendar/film"
MAX_SERIES = 25

TIME_RE = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m\.?$", re.I)
DATE_RE = re.compile(r"^(?:[A-Z][a-z]{2,8},?\s+)?([A-Z][a-z]{2,8})\.?\s+(\d{1,2})$")
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug",
                                       "sep", "oct", "nov", "dec"], 1)}


def parse_time(text: str):
    m = TIME_RE.match(text.replace("\xa0", " ").strip())
    if not m:
        return None
    h, mi = int(m.group(1)) % 12, int(m.group(2) or 0)
    return h + (12 if m.group(3).lower() == "p" else 0), mi


def infer_day(month_name: str, day: int, ref: date) -> date | None:
    """'Dec 30' has no year: pick the year that puts it nearest to (and preferably after) ref."""
    mon = MONTHS.get(month_name[:3].lower())
    if not mon:
        return None
    cands = []
    for y in (ref.year - 1, ref.year, ref.year + 1):
        try:
            cands.append(date(y, mon, day))
        except ValueError:
            pass
    return min(cands, key=lambda d: abs((d - ref).days + 30))   # bias toward the future


def parse_title_line(p: Tag) -> tuple[list[str], int | None, str | None]:
    titles = [clean_text(em.get_text(" ")) for em in p.find_all("em")]
    rest = p.get_text(" ")
    for em in p.find_all("em"):
        rest = rest.replace(em.get_text(" "), "", 1)
    rest = clean_text(rest) or ""
    year = director = None
    if m := re.search(r"\b((?:18|19|20)\d{2})\b", rest):
        year = int(m.group(1))
    if m := re.search(r"Directed by (.+?)(?:\.\s|\.?$)", rest):
        director = clean_text(m.group(1))
    return [t for t in titles if t], year, director


def parse_listing(html: str, ref: date, h1_is_series: bool = True) -> list[dict]:
    """h1_is_series=False for the /calendar/film index, whose <h1> is just 'Film'."""
    soup = BeautifulSoup(html, "lxml")
    h1 = soup.find("h1")
    series = clean_text(h1.get_text(" ")) if h1 and h1_is_series else None
    rows, current = [], None
    for node in soup.find_all(["h2", "h3", "a"]):
        if node.name in ("h2", "h3"):
            m = DATE_RE.match(clean_text(node.get_text(" ")) or "")
            if m:
                current = infer_day(m.group(1), int(m.group(2)), ref)
            continue
        href = node.get("href") or ""
        if not current or not re.match(r"^(https://www\.moma\.org)?/calendar/events/\d+", href):
            continue
        titles, year, director, tm, notes, screen = [], None, None, None, [], None
        for p in node.find_all("p"):
            text = clean_text(p.get_text(" ")) or ""
            if p.find("em") and not tm:
                t, y, d = parse_title_line(p)
                titles += t
                year, director = year or y, director or d
            elif (hm := parse_time(text)) and not tm:
                tm = hm
            elif re.search(r"\bMoMA\b|Floor|Theater", text):
                screen = text
            elif text:
                notes.append(text)
        if not titles or not tm:
            continue
        rows.append({
            "title": " + ".join(titles), "year": year if len(titles) == 1 else None,
            "director": director, "start": to_local(datetime(current.year, current.month, current.day, *tm)),
            "note": "; ".join(notes) or None, "screen": screen, "series": series,
            "detail_url": urljoin(SITE, href),
        })
    return rows


def series_links(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    links = [urljoin(SITE, a["href"].split("?")[0]) for a in soup.select('a[href*="/calendar/film/"]')
             if re.search(r"/calendar/film/\d+", a["href"])]
    return list(dict.fromkeys(links))[:MAX_SERIES]


@register("moma")
class MomaScraper(BaseScraper):
    needs_browser = True

    def fetch(self) -> list[RawPage]:
        first = self.browser_page(START)
        pages = [first]
        for url in series_links(first.body):
            pages.append(self.browser_page(url))
        return pages

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        out = []
        for page in pages:
            is_index = page.url.rstrip("/").endswith("/calendar/film")
            for r in parse_listing(page.body, ref_date(page), h1_is_series=not is_index):
                start_s = iso(r["start"])
                out.append(Screening(
                    id=make_id(self.venue.id, start_s, r["title"]),
                    venue_id=self.venue.id, title=r["title"], start=start_s,
                    day=r["start"].date().isoformat(), director=r["director"], year=r["year"],
                    series=r["series"], screen=r["screen"], note=r["note"],
                    detail_url=r["detail_url"], scraped_at=page.fetched_at,
                ))
        # the index repeats a few rows that series pages also list; prefer the series version
        best: dict[str, Screening] = {}
        for s in out:
            if s.id not in best or (s.series and not best[s.id].series):
                best[s.id] = s
        return list(best.values())
