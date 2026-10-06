"""Bryn Mawr Film Institute — WordPress pages over Agile Ticketing (SOURCES.md §11).

Three kinds of page, all server-rendered:
  * /films/week/            the next ~8 days: <h5> date headings, then per film <b><a>TITLE</a></b>
                            "(R) USA – 1 hr 50 min" and its times (a.showtime, or span.showtime-past);
  * /films/?view=list       every programme with its dates ("Oct 6 – 15", "Oct 10 & 31", "Nov 7") and no times;
  * /event/<slug>/          one programme: credits ("1961 · d. John Huston"), series, and a "Buy Tickets"
                            box with <b>Tuesday, October 13</b> followed by that day's times.
The week page gives the near days; event pages are fetched for programmes that also play after it, within
the horizon (live: their times are what we read). Courses and seminars ("Instructor: …") are not
screenings and are skipped.

Times carry no am/pm except morning shows, which the site marks ("11.00am"): an unmarked time is pm.
A label after a time is that showing's note ("7.30 Open Caption", "1.00 SF" = sensory friendly).
The Agile ticketing behind the site exposes no usable public feed (PLATFORMS.md §3).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from bs4 import BeautifulSoup, NavigableString, Tag

from ..base import BaseScraper
from ..models import RawPage, Screening
from ..normalize import (clean_text, end_from_runtime, iso, make_id, nearest_date, normalize_format, smart_title,
                         title_case_runs, to_local)
from ..registry import register

SITE = "https://brynmawrfilm.org"
WEEK_URL = f"{SITE}/films/week/"
LIST_URL = f"{SITE}/films/?view=list"
MAX_EVENT_PAGES = 30

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DAY_HEADING = re.compile(r"([A-Z][a-z]+)\s+(\d{1,2})\s*$")                  # "Today · Tuesday, October 6"
TIME = re.compile(r"^(\d{1,2})[.:](\d{2})\s*(am|pm)?\s*(.*)$", re.I)
RUNTIME = re.compile(r"(?:(\d+)\s*hr)?\s*(?:(\d+)\s*min)?", re.I)
CREDIT = re.compile(r"\b((?:18|19|20)\d{2})\s*·\s*d\.\s*(.+)$")              # "1961 · d. John Huston"
LABELS = {"open caption": "Open caption", "sf": "Sensory friendly"}


title_case = title_case_runs


def runtime_min(text: str) -> int | None:
    m = re.search(r"(\d+)\s*hr(?:\s*(\d+)\s*min)?|(\d+)\s*min", text or "")
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2) or 0) if m.group(1) else int(m.group(3))


def notes_from(text: str) -> list[str]:
    return ["Subtitled"] if re.search(r"\bwith subtitles\b", text or "", re.I) else []


def parse_time(token: str) -> tuple[int, int, str | None] | None:
    """'7.30 Open Caption' -> (19, 30, 'Open caption'); '11.00am' -> (11, 0, None); unmarked = pm."""
    m = TIME.match(clean_text(token) or "")
    if not m:
        return None
    h, mi, ampm, label = int(m.group(1)), int(m.group(2)), (m.group(3) or "").lower(), clean_text(m.group(4))
    if ampm == "am":
        h = 0 if h == 12 else h
    elif h < 12:
        h += 12
    return h, mi, (LABELS.get(label.lower(), label) if label else None)


def day_of(text: str, ref: date) -> date | None:
    m = DAY_HEADING.search(clean_text(text) or "")
    month = MONTHS.get(m.group(1)[:3].lower()) if m else None
    return nearest_date(month, int(m.group(2)), ref) if month else None


def list_dates(text: str, ref: date) -> list[date]:
    """'Oct 6 – 15' / 'Oct 12 – Nov 30' -> first and last day; 'Oct 10 & 31' / 'Nov 28 & Dec 12' -> both days."""
    out, month = [], None
    for tok in re.findall(r"[A-Za-z]{3,}|\d{1,2}", text or ""):
        if tok[:3].lower() in MONTHS:
            month = MONTHS[tok[:3].lower()]
        elif month and (d := nearest_date(month, int(tok), ref)):
            out.append(d)
    return out


def parse_list(html: str, ref: date) -> list[dict]:
    """Programmes on the list view: {url, title, first, last} (courses and seminars left out)."""
    out = []
    for tr in BeautifulSoup(html, "lxml").select("div.primary tr"):
        tds = tr.find_all("td")
        a = tds[1].select_one("b a[href]") if len(tds) >= 2 else None
        if not a or "Instructor:" in tds[1].get_text(" "):
            continue
        days = list_dates(tds[0].get_text(" ", strip=True), ref)
        if days:
            out.append({"url": a["href"], "title": title_case(a.get_text(" ", strip=True)), "first": min(days), "last": max(days)})
    return out


def event_title(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """A programme page's <h2>: (title, subtitle) — '<h2>THE LONG GOODBYE<div class="subtitle">On 35mm</div>'."""
    head = soup.select_one("div.primary h2")
    if not head:
        return None, None
    sub = head.select_one(".subtitle")
    subtitle = clean_text(sub.get_text(" ")) if sub else None
    title = clean_text("".join(t for t in head.find_all(string=True, recursive=True)
                               if not (sub and t.find_parent(class_="subtitle"))))
    return title_case(title), subtitle


def parse_event_info(html: str) -> dict:
    """Credits of one programme page: director, year, runtime_min, series, format, notes."""
    soup = BeautifulSoup(html, "lxml")
    info: dict = {"notes": []}
    head = soup.select_one("div.primary h2")
    subtitle = event_title(soup)[1]
    if subtitle and (fmt := re.search(r"\b(16|35|70)\s*mm\b", subtitle, re.I)):
        info["format"] = normalize_format(f"{fmt.group(1)}mm")
    block = head.find_next("p") if head else None
    if block:
        series = block.select_one("a[href*='/series/']")
        if series:
            info["series"] = clean_text(series.get_text(" "))
        for line in (clean_text(x) for x in block.get_text("\n").split("\n")):
            if not line:
                continue
            if m := CREDIT.search(line):
                info["year"], info["director"] = int(m.group(1)), clean_text(m.group(2))
            elif re.search(r"\d+\s*(?:hr|min)\b", line) and "runtime_min" not in info:
                info["runtime_min"] = runtime_min(line)
                info["notes"] += notes_from(line)
    for tag in soup.select("div.tags a"):
        if fmt := re.fullmatch(r"(16|35|70)\s*mm", (tag.get_text(strip=True) or "").lower()):
            info["format"] = normalize_format(f"{fmt.group(1)}mm")
    return info


def walk_times(container: Tag, ref: date):
    """(date, title_link, time_node) in document order: date headings (<h5> or <b>Weekday, Month D</b>),
    the programme link that precedes its times, and each a.showtime / span.showtime-past."""
    day, film = None, None
    for node in container.descendants:
        if not isinstance(node, Tag):
            continue
        if node.name in ("h5", "b") and not node.find("a") and (d := day_of(node.get_text(" ", strip=True), ref)):
            day = d
        elif node.name == "a" and node.parent.name == "b" and "/event/" in (node.get("href") or ""):
            film = node
        elif "showtime" in (node.get("class") or []) or "showtime-past" in (node.get("class") or []):
            yield day, film, node


@register("brynmawr")
class BrynMawrScraper(BaseScraper):
    def fetch(self) -> list[RawPage]:
        week = self.get_page(WEEK_URL)
        listing = self.get_page(LIST_URL)
        ref = today_of(week.fetched_at, self.tz)
        covered = max((d for d, _, _ in walk_times(primary(week.body), ref) if d), default=ref)
        until = ref + timedelta(days=self.venue.horizon_days)
        later = [p for p in parse_list(listing.body, ref) if p["last"] > covered and p["first"] <= until]
        pages = [week, listing]
        for p in sorted(later, key=lambda p: max(p["first"], covered))[:MAX_EVENT_PAGES]:
            pages.append(self.get_page(p["url"]))
        return pages

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        week = next((p for p in pages if p.url.rstrip("/").endswith("/films/week")), None)
        events = [p for p in pages if "/event/" in p.url]
        ref = today_of((week or pages[0]).fetched_at, self.tz)
        info = {canon(p.url): parse_event_info(p.body) for p in events}
        covered = max((d for d, _, _ in walk_times(primary(week.body), ref) if d), default=None) if week else None
        out = []
        sources = ([(week, None)] if week else []) + [(p, canon(p.url)) for p in events]
        for page, own_url in sources:
            box = primary(page.body) if own_url is None else BeautifulSoup(page.body, "lxml").select_one("div.buy-tickets")
            if box is None:
                continue
            page_title = event_title(BeautifulSoup(page.body, "lxml"))[0] if own_url else None
            for day, film, node in walk_times(box, ref):
                if day is None or (own_url and covered and day <= covered):
                    continue                                   # the week page already has these days
                url = canon(film["href"]) if film is not None and own_url is None else own_url
                title = title_case(film.get_text(" ", strip=True)) if own_url is None and film is not None else page_title
                parsed = parse_time(node.get_text(" ", strip=True))
                if not title or not parsed:
                    continue
                h, mi, label = parsed
                start = to_local(datetime(day.year, day.month, day.day, h, mi), self.tz)
                start_s = iso(start, self.tz)
                meta = info.get(url, {})
                line = film_line(film) if own_url is None and film is not None else ""
                rt = meta.get("runtime_min") or runtime_min(line)
                notes = list(dict.fromkeys(([label] if label else []) + meta.get("notes", []) + notes_from(line)))
                out.append(Screening(
                    id=make_id(self.venue.id, start_s, title), venue_id=self.venue.id, title=title,
                    start=start_s, day=start_s[:10], end=end_from_runtime(start, rt, self.tz),
                    director=meta.get("director"), year=meta.get("year"), runtime_min=rt,
                    format=meta.get("format"), series=meta.get("series"), note="; ".join(notes) or None,
                    detail_url=url, ticket_url=node.get("href") or url, scraped_at=page.fetched_at))
        return out

    def enrich(self, screenings: list[Screening]) -> None:
        """Credits for the films only on the week page (their event pages are cached for a week)."""
        missing = [s for s in screenings if not s.director and not s.year]
        if missing:
            self.enrich_by_url(missing, parse_event_info, fields=("director", "year", "runtime_min", "series", "format"))


def primary(html: str) -> Tag:
    soup = BeautifulSoup(html, "lxml")
    return soup.select_one("div.content div.primary") or soup.select_one("div.primary") or soup


def film_line(link: Tag) -> str:
    """The text right after a programme's title link on the week page: '(R) USA – 2 hr 2 min – with subtitles'."""
    parts = []
    for sib in link.parent.next_siblings:
        if isinstance(sib, Tag) and sib.name == "br":
            break
        parts.append(sib if isinstance(sib, NavigableString) else sib.get_text(" "))
    return clean_text(" ".join(parts)) or ""


def canon(url: str) -> str:
    return url.split("?")[0].rstrip("/") + "/"


def today_of(fetched_at: str, tz) -> date:
    return to_local(datetime.fromisoformat(fetched_at.replace("Z", "+00:00")), tz).date()
