"""Philadelphia Film Society — Agile Ticketing's public event feed (SOURCES.md §9).

filmadelphia.org itself sits behind a WAF that blocks every non-browser client, but their ticketing
provider publishes an official JSON feed (documented at agiletix.com/api) that lists every show and
showing across the Film Center, Bourse and East. Agile asks feed users to fetch server-side and cache;
it refreshes every 10 minutes and we read it twice a day.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from ..base import BaseScraper
from ..models import RawPage, Screening
from ..normalize import clean_text, end_from_runtime, iso, make_id, normalize_format, smart_title, to_local
from ..registry import register

FEED = "https://prod5.agileticketing.net/websales/feed.ashx"
EVENTS_GUID = "6634566a-a49f-4dec-89e6-bb4c5eda4814"      # "Philadelphia Film Society - EVENTS" entry point
GENERIC_TYPES = {"first-run", "curated", "special event", ""}
NOTE_SPLIT = re.compile(r"\s+(w/|with)\s+(.*(?:Q&A|intro|introduction|discussion|conversation|live).*)$", re.I)


def props(show: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for p in show.get("CustomProperties") or []:
        if p.get("Hidden"):
            continue
        v = clean_text(str(p.get("Value") or ""))
        if v and v.strip("?").upper() not in ("", "TBA", "TBD", "N/A", "NA", "UNKNOWN"):   # mystery screenings use "?"
            out.setdefault(p.get("Name") or "", []).append(v)
    return out


def split_title(name: str) -> tuple[str, str | None]:
    """'I LOVE BOOSTERS w/ Q&A' -> ('I Love Boosters', 'w/ Q&A')."""
    name = clean_text(name) or ""
    note = None
    if m := NOTE_SPLIT.search(name):
        name, note = name[:m.start()], f"{m.group(1)} {m.group(2)}"
    return smart_title(name), note


@register("filmadelphia")
class FilmadelphiaScraper(BaseScraper):
    def fetch(self) -> list[RawPage]:
        return [self.get_page(FEED, ext="json", params={
            "guid": self.venue.extra.get("agile_guid") or EVENTS_GUID,
            "showslist": "true", "withmedia": "false", "format": "json", "v": "latest"})]

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        out = []
        for page in pages:
            for show in json.loads(page.body).get("ArrayOfShows") or []:
                title, title_note = split_title(show.get("Name") or "")
                if not title:
                    continue
                p = props(show)
                runtime = _int((p.get("Run Time") or [None])[0]) or _int(show.get("Duration"))
                if runtime and not 1 <= runtime <= 360:
                    runtime = None                  # placeholders like 585 for "Surprise 35!"
                year = _int((p.get("Release Year") or [None])[0])
                director = ", ".join(smart_title(d) for d in p.get("Director", [])) or None
                fmt = normalize_format((p.get("Format") or [None])[0])
                langs = [l.title() for l in p.get("Original Language", [])]
                language = ", ".join(dict.fromkeys(langs)) or None
                series = smart_title((p.get("Film Series") or [None])[0])
                if not series and (show.get("Type") or "").strip().lower() not in GENERIC_TYPES:
                    series = smart_title(re.sub(r"\s+:\s*", ": ", clean_text(show["Type"])))  # "Director Series : X"
                for sh in show.get("CurrentShowings") or []:
                    if sh.get("DateTBD") or sh.get("ContentDelivery", "InPerson") != "InPerson":
                        continue
                    try:
                        start = to_local(datetime.fromisoformat(sh["StartDate"]))
                    except (KeyError, ValueError):
                        continue
                    end = None
                    if sh.get("EndDate"):
                        try:
                            end_dt = to_local(datetime.fromisoformat(sh["EndDate"]))
                            if 0 < (end_dt - start).total_seconds() <= 6 * 3600:   # "Surprise 35!" ends 585 min later
                                end = iso(end_dt)
                        except ValueError:
                            pass
                    start_s = iso(start)
                    notes = [n for n in (title_note, clean_text(sh.get("ShortDescriptive"))) if n]
                    out.append(Screening(
                        id=make_id(self.venue.id, start_s, title),
                        venue_id=self.venue.id, title=title, start=start_s, day=start.date().isoformat(),
                        end=end or end_from_runtime(start, runtime),
                        director=director, year=year, runtime_min=runtime, format=fmt, language=language,
                        series=series,
                        screen=clean_text((sh.get("Venue") or {}).get("Name")),
                        note="; ".join(notes) or None,
                        detail_url=show.get("InfoLink") or None,
                        ticket_url=sh.get("LegacyPurchaseLink") or None,
                        scraped_at=page.fetched_at,
                    ))
        return out


def _int(v) -> int | None:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None
