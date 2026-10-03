"""Agile Ticketing — the public event feed (PLATFORMS.md §3).

    source: {adapter: agile, guid: <feed GUID>, host: prod5.agileticketing.net}

GET https://<host>/websales/feed.ashx?guid=<GUID>&showslist=true&withmedia=false&format=json&v=latest

Agile documents the feed for third-party sites (agiletix.com/api): it refreshes every 10 minutes and
asks users to fetch server-side and cache, which a twice-daily scrape does. Hosts come in pairs
(prod1/2, prod3/4, prod5/6) or a cinema's own domain (store.coolidge.org); the wrong cluster answers
HTTP 200 with an HTML session-timeout page, so a response only counts if it parses as JSON.

GUIDs: the `evtinfo=<id>~<guid>` in purchase links is NOT a feed GUID. An `epguid=` entry-point GUID
sometimes is (Coral Gables); otherwise the cinema has to supply one from Agile's back office.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import urlparse

from ..base import BaseScraper, ScrapeError
from ..models import RawPage, Screening
from ..normalize import (clean_text, end_from_runtime, iso, language_from_text, make_id, normalize_format,
                         smart_title, to_local)
from . import Candidate, register_adapter

FEED_PATH = "/websales/feed.ashx"
FEED_PARAMS = {"showslist": "true", "withmedia": "false", "format": "json", "v": "latest"}
CLUSTERS = [f"prod{n}.agileticketing.net" for n in range(1, 7)]
GENERIC_TYPES = {"first-run", "curated", "special event", "repertory", "new releases", "events", ""}
NOTE_SPLIT = re.compile(r"\s+(w/|with)\s+(.*(?:Q&A|intro|introduction|discussion|conversation|live).*)$", re.I)
GUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
PLACEHOLDERS = ("", "TBA", "TBD", "N/A", "NA", "UNKNOWN")



OPEN_CAPTIONS = "Open captions"            # same wording as Film at Lincoln Center's flag


def open_captioned(showing: dict) -> bool:
    """Agile marks open-caption showings (PFS: its Tuesday first-run shows) with a *hidden* per-showing
    property: {"Group": "Accessibility", "Name": "Amenities", "Value": "Open Captioning"}."""
    return any(re.search(r"open[\s-]*caption", str(p.get("Value") or ""), re.I)
               for p in showing.get("CustomProperties") or [])

def props(show: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for p in show.get("CustomProperties") or []:
        if p.get("Hidden"):
            continue
        v = clean_text(str(p.get("Value") or ""))
        if v and v.strip("?").upper() not in PLACEHOLDERS:       # mystery screenings use "?"
            out.setdefault((p.get("Name") or "").strip().lower(), []).append(v)
    return out


def first(p: dict, *names: str) -> str | None:
    for n in names:
        if p.get(n):
            return p[n][0]
    return None


def split_title(name: str) -> tuple[str, str | None]:
    """'I LOVE BOOSTERS w/ Q&A' -> ('I Love Boosters', 'w/ Q&A')."""
    name = clean_text(name) or ""
    note = None
    if m := NOTE_SPLIT.search(name):
        name, note = name[:m.start()], f"{m.group(1)} {m.group(2)}"
    return smart_title(name), note


def _int(v) -> int | None:
    m = re.match(r"\s*(\d+)", str(v or ""))
    return int(m.group(1)) if m else None


def _language(p: dict) -> str | None:
    """'Original Language: French' (PFS) or 'Language: Italian with English subtitles' (Coral Gables)."""
    langs = []
    for v in p.get("original language", []) + p.get("language", []):
        text = v if v.lower().startswith("in ") else f"In {v}"          # "Italian with English subtitles"
        langs.append(language_from_text(text) or (v.title() if v.isupper() or v.islower() else v))
    return ", ".join(dict.fromkeys(l for l in langs if l)) or None


def is_feed(body: str) -> bool:
    try:
        return isinstance(json.loads(body), dict)
    except ValueError:
        return False


def feed_url(host: str) -> str:
    return f"https://{host}{FEED_PATH}"


@register_adapter("agile")
class AgileAdapter(BaseScraper):
    PARAMS = {"guid": str}
    OPTIONAL_PARAMS = {"host": str}
    DETECT_ORDER = 30

    def fetch(self) -> list[RawPage]:
        guid = self.params["guid"]
        hosts = [self.params["host"]] if self.params.get("host") else CLUSTERS
        for host in hosts:
            page = self.get_page(feed_url(host), ext="json", params={"guid": guid, **FEED_PARAMS})
            if is_feed(page.body):
                return [page]
        raise ScrapeError(f"no Agile cluster answered with a JSON feed for guid {guid}")

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        out = []
        for page in pages:
            for show in json.loads(page.body).get("ArrayOfShows") or []:
                out.extend(self._show(show, page))
        return out

    def _show(self, show: dict, page: RawPage) -> list[Screening]:
        title, title_note = split_title(show.get("Name") or "")
        if not title:
            return []
        p = props(show)
        runtime = _int(first(p, "run time", "runtime")) or _int(show.get("Duration"))
        if runtime and not 1 <= runtime <= 360:
            runtime = None                      # placeholders like 585 for "Surprise 35!"
        year = _int(first(p, "release year", "year"))
        director = ", ".join(smart_title(d) for d in p.get("director", [])) or None
        fmt = normalize_format(first(p, "format"))
        series = smart_title(first(p, "film series", "series"))
        if not series and (show.get("Type") or "").strip().lower() not in GENERIC_TYPES:
            series = smart_title(re.sub(r"\s+:\s*", ": ", clean_text(show["Type"])))   # "Director Series : X"
        out = []
        for sh in show.get("CurrentShowings") or []:
            if sh.get("DateTBD") or sh.get("ContentDelivery", "InPerson") != "InPerson":
                continue
            try:
                start = to_local(datetime.fromisoformat(sh["StartDate"]), self.tz)
            except (KeyError, TypeError, ValueError):
                continue
            end = None
            if sh.get("EndDate"):
                try:
                    end_dt = to_local(datetime.fromisoformat(sh["EndDate"]), self.tz)
                    if 0 < (end_dt - start).total_seconds() <= 6 * 3600:   # "Surprise 35!" ends 585 min later
                        end = iso(end_dt, self.tz)
                except ValueError:
                    pass
            start_s = iso(start, self.tz)
            notes = [n for n in (title_note, clean_text(sh.get("ShortDescriptive"))) if n]
            if open_captioned(sh):
                notes.append(OPEN_CAPTIONS)
            out.append(Screening(
                id=make_id(self.venue.id, start_s, title),
                venue_id=self.venue.id, title=title, start=start_s, day=start.date().isoformat(),
                end=end or end_from_runtime(start, runtime),
                director=director, year=year, runtime_min=runtime, format=fmt, language=_language(p),
                series=series,
                screen=clean_text((sh.get("Venue") or {}).get("Name")),
                note="; ".join(notes) or None,
                detail_url=show.get("InfoLink") or None,
                ticket_url=sh.get("LegacyPurchaseLink") or None,
                scraped_at=page.fetched_at,
            ))
        return out

    @classmethod
    def detect(cls, probe) -> Candidate | None:
        links = [u for u in probe.links() if "/websales/" in u.lower() or "agileticketing" in u.lower()]
        if not links and not probe.find(r"agileticketing\.net|agiletix"):
            return None
        hosts = list(dict.fromkeys(urlparse(u).netloc.lower() for u in links if "/websales/" in u.lower()))
        # programme-list entry points first; login / membership / donation entry points never list shows
        ranked = sorted(links, key=lambda u: 0 if "list.aspx" in u.lower() else 1)
        guids = list(dict.fromkeys(g.lower() for u in ranked if not re.search(r"login|member|donat", u, re.I)
                                   for g in re.findall(rf"epguid=({GUID})", u, re.I)))
        evidence = [f"Agile Ticketing links on the site ({', '.join(hosts[:3]) or 'agileticketing.net'})"]
        if not guids:
            probe.hints.append("agile_no_feed_guid")
            return None
        # the host the site links to first, then the other clusters; a JSON answer settles the host
        order = hosts + [h for h in CLUSTERS if h not in hosts]
        for guid in guids[:3]:
            for host in order[:3]:
                r = probe.get(f"{feed_url(host)}?guid={guid}&" + "&".join(f"{k}={v}" for k, v in FEED_PARAMS.items()))
                if r is None:
                    break
                if r.status != 200 or not is_feed(r.text):
                    continue
                if json.loads(r.text).get("ArrayOfShows"):
                    return Candidate("agile", {"guid": guid, "host": host},
                                     evidence + [f"epguid {guid} returns a feed with shows on {host}"],
                                     order=cls.DETECT_ORDER)
                break                                   # right cluster, but this entry point lists no shows
        probe.hints.append("agile_no_feed_guid")
        return None
