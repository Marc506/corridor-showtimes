"""BAM Rose Cinemas — open JSON calendar API (SOURCES.md §1)."""
from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import datetime, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..base import DETAIL_TTL, BaseScraper
from ..models import RawPage, Screening
from ..normalize import (clean_text, iso, language_from_text, make_id, normalize_format, parse_iso, to_local,
                         today_local)
from ..registry import register

API = "https://www.bam.org/api/BAMApi/GetCalendarEventsByDayWithOnGoing"
SITE = "https://www.bam.org"
SOON = timedelta(days=3)            # pages of films this close are re-read daily: schedules and guests get added late
SOON_TTL = timedelta(hours=20)

# A day-long programme's description may carry its running order (SOURCES.md §1):
#   "Schedule:" / "12:15 pm" / "Mother Hunger dir. Joie Lee" / "12:45pm" / "Conversation with …" / …
TIME_LINE = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?$", re.I)
DIR_LINE = re.compile(r"^(.+?),?\s+(?:dir\.?|directed by)\s+(.+)$", re.I)
YEAR_LINE = re.compile(r"^(.+?)\s*\(((?:18|19|20)\d{2})\)$")
PRESENTS = re.compile(r"^.{3,80}?\s+presents:?\s+", re.I)
WORKS_OF = re.compile(r"^(?:the )?(?:works|films|shorts|cinema) (?:of|by) (.+)$", re.I)


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
    desc = BeautifulSoup(html, "lxml").select_one(".heroInfoLeft .description")
    if desc and (schedule := parse_schedule(desc.get_text("\n", strip=True))):
        out["schedule"] = schedule
    return out


def parse_schedule(text: str) -> list[dict] | None:
    """The lines after "Schedule:" as [{"time": (hour, minute), "lines": [...]}, …]; None without one."""
    _, sep, rest = text.partition("Schedule:")
    blocks: list[dict] = []
    for line in rest.split("\n") if sep else []:
        line = clean_text(line)
        if not line:
            continue
        if m := TIME_LINE.match(line):
            hour = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "p" else 0)
            blocks.append({"time": (hour, int(m.group(2) or 0)), "lines": []})
        elif blocks:
            blocks[-1]["lines"].append(line)
    return blocks if len(blocks) >= 2 else None


def block_films(lines: list[str]) -> dict | None:
    """One schedule block -> {films: [(title, director, year)], header, extra}, or None when nothing in it is a
    film (opening remarks, conversations, a break, a town hall). A film line names its director ("Heat dir. Aicha
    Cherif") or its year ("Boyant (2008)"); a line before the first film names the set ("The Works of Akosua
    Adoma Owusu"); lines after the films are kept as notes ("*pre-recorded")."""
    films, header, extra = [], None, []
    for line in lines:
        if m := DIR_LINE.match(line):
            films.append((clean_text(m.group(1)), clean_text(m.group(2)), None))
        elif m := YEAR_LINE.match(line):
            films.append((clean_text(m.group(1)), None, int(m.group(2))))
        elif not films and header is None:
            header = line
        else:
            extra.append(line)
    return {"films": films, "header": header, "extra": extra} if films else None


def programme_name(title: str) -> str:
    """'New Negress Film Society presents Black Women's Film Conference 2026' -> "Black Women's Film Conference
    2026": the presenter is not what is on screen."""
    return PRESENTS.sub("", title).strip() or title


def split_programme(s: Screening, schedule: list[dict], tz) -> list[Screening] | None:
    """A one-day programme with a running order -> one row per film block, each ending when the next block starts;
    talks and breaks are left out. A block of one film is titled by the film; a block of several (a set of shorts)
    by the programme's name, with each film in the note. None when the schedule doesn't fit this screening (it
    starts more than 90 minutes away from the listed start, or its times don't run forward)."""
    start = parse_iso(s.start, tz)
    times = [to_local(datetime(start.year, start.month, start.day, *b["time"]), tz) for b in schedule]
    if abs(times[0] - start) > timedelta(minutes=90) or any(b <= a for a, b in zip(times, times[1:])):
        return None
    out = []
    for i, block in enumerate(schedule):
        if not (b := block_films(block["lines"])):
            continue
        films = b["films"]
        directors = list(dict.fromkeys(d for _, d, _ in films if d))
        if len(films) == 1:
            title, year, notes = films[0][0], films[0][2], [b["header"]]
        else:
            if not directors and b["header"] and (m := WORKS_OF.match(b["header"])):
                directors = [clean_text(m.group(1))]
            listed = "; ".join(f"{t} ({y})" if y else f"{t} (dir. {d})" if d else t for t, d, y in films)
            title, year = programme_name(s.title), None
            notes = [f"{b['header']}: {listed}" if b["header"] else listed]
        begin = iso(times[i], tz)
        out.append(replace(
            s, id=make_id(s.venue_id, begin, title), title=title, start=begin,
            end=iso(times[i + 1], tz) if i + 1 < len(times) else None, director=", ".join(directors) or None,
            year=year, runtime_min=None, series=s.title,
            note="; ".join(filter(None, notes + b["extra"] + [s.note])) or None))
    return out or None


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
        soon = datetime.now().astimezone() + SOON
        near = {s.detail_url for s in screenings if parse_iso(s.start, self.tz) < soon}
        info = self.enrich_by_url(screenings, parse_detail,
                                  fields=("director", "year", "runtime_min", "format", "series", "language"),
                                  ttl=lambda url: SOON_TTL if url in near else DETAIL_TTL)
        per_url: dict = {}
        for s in screenings:
            per_url[s.detail_url] = per_url.get(s.detail_url, 0) + 1
        out = []
        for s in screenings:
            schedule = (info.get(s.detail_url) or {}).get("schedule")
            parts = split_programme(s, schedule, self.tz) if schedule and per_url[s.detail_url] == 1 else None
            out.extend(parts or [s])
        screenings[:] = out
