"""screenslate.com (SOURCES.md §10) — usually a venue's `fallback: {adapter: screenslate, nid: <n>}`.

Used when a venue's primary source fails (run.py); NYC / SF venues behind a firewall can also use it as
their only source. Two endpoints:
  /api/screenings/date?date=YYYYMMDD&field_venue_target_id=<nid>  -> [{nid, field_time, field_note, field_timestamp}]
  /api/screenings/id/<nid>+<nid>...                                 -> programme details
Their WAF rejects Python's TLS handshake, so this source uses the curl transport.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup

from ..base import BaseScraper
from ..models import RawPage, Screening
from ..normalize import (now_utc_iso, clean_text, end_from_runtime, iso, make_id, normalize_format,
                         to_local, today_local, zone)
from . import register_adapter

API = "https://www.screenslate.com/api/screenings"
MAX_DAYS = 45                 # screenslate rarely lists further out
EMPTY_STREAK_STOP = 10        # stop walking forward after this many empty days (once data was seen)
BATCH = 40
MIN_INTERVAL_S = 0.7          # screenslate's own pacing, independent of the venue's rate_limit_s
# screenslate's format vocabulary (lower-cased)
SS_FORMATS = {"dcp", "35mm", "16mm", "70mm", "8mm", "super 8", "vhs", "digital", "digital video",
              "blu-ray", "dvd", "4k dcp", "2k dcp", "35mm-to-dcp", "16mm-to-dcp"}


def _html_text(fragment: str | None) -> str | None:
    return clean_text(BeautifulSoup(fragment, "lxml").get_text(" ")) if fragment else None


def _split(fragment: str | None) -> list[str]:
    return [p for p in (fragment or "").split("|") if p.strip()]


def parse_films(rec: dict) -> list[dict]:
    """media_title_labels / media_title_info are '|'-separated, in the same order.
    info chunk: <span>Director</span><span>1997</span><span>96M</span><span>DCP</span> (any may be missing)."""
    titles = [_html_text(p) for p in _split(rec.get("media_title_labels"))]
    infos = _split(rec.get("media_title_info"))
    films = []
    for i, t in enumerate(titles):
        f = {"title": t, "director": None, "year": None, "runtime_min": None, "format": None}
        if i < len(infos):
            spans = [clean_text(s.get_text(" ")) for s in BeautifulSoup(infos[i], "lxml").find_all("span")]
            for sp in filter(None, spans):
                if re.fullmatch(r"(18|19|20)\d{2}", sp):
                    f["year"] = int(sp)
                elif m := re.fullmatch(r"(\d+)\s*M(in)?", sp, re.I):
                    f["runtime_min"] = int(m.group(1))
                elif sp.lower() in SS_FORMATS or f["director"] is not None:
                    f["format"] = normalize_format(sp)
                else:
                    f["director"] = sp
        films.append(f)
    return films


def programme_title(rec: dict, films: list[dict]) -> str | None:
    display = clean_text(rec.get("field_display_title"))
    if display:
        return display
    names = [f["title"] for f in films if f["title"]]
    if len(names) == 1:
        return names[0]
    if 1 < len(names) <= 3:
        return " + ".join(names)
    if len(names) > 3:
        return f"{names[0]} + {names[1]} + {len(names) - 2} more"
    # last resort: the editors' internal title, minus " at AFA" / " moma" style suffixes
    raw = clean_text(rec.get("title"))
    return re.sub(r"\s+(at\s+\w+|moma)$", "", raw or "", flags=re.I) or None


def parse_start(item: dict, tz=None) -> datetime | None:
    ts = str(item.get("field_timestamp") or "").strip()
    if re.fullmatch(r"\d{9,11}", ts):                       # unix seconds (older API shape)
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(zone(tz))
    try:
        return to_local(datetime.fromisoformat(ts), tz)       # "2026-09-26T12:15:00", venue-local
    except ValueError:
        return None


@register_adapter("screenslate")
class ScreenslateScraper(BaseScraper):
    source = "screenslate"
    transport = "curl"
    enforce_budget = False        # one GET per day of horizon; paced by MIN_INTERVAL_S instead
    PARAMS = {"nid": int}

    @property
    def raw_name(self) -> str:
        return f"{self.venue.id}_screenslate"

    def get_page(self, url: str, ext: str = "html", params: dict | None = None) -> RawPage:
        r = self.client.get(url, min_interval=MIN_INTERVAL_S, params=params, transport=self.transport)
        return RawPage(url=str(r.url), body=r.text, fetched_at=now_utc_iso(), ext=ext)

    def fetch(self) -> list[RawPage]:
        nid = self.params.get("nid") or self.venue.screenslate_nid
        if not nid:
            raise ValueError(f"{self.venue.id} has no screenslate nid")
        pages, nids, seen_any, empty = [], [], False, 0
        start = today_local(self.tz)
        for i in range(min(self.venue.horizon_days, MAX_DAYS) + 1):
            d = start + timedelta(days=i)
            page = self.get_page(f"{API}/date", ext="json", params={
                "_format": "json", "date": d.strftime("%Y%m%d"), "field_venue_target_id": nid})
            items = _loads(page.body)
            pages.append(page)
            nids += [str(x["nid"]) for x in items if x.get("nid")]
            if items:
                seen_any, empty = True, 0
            else:
                empty += 1
                if seen_any and empty >= EMPTY_STREAK_STOP:
                    break
        unique = list(dict.fromkeys(nids))
        for i in range(0, len(unique), BATCH):
            pages.append(self.get_page(f"{API}/id/{'+'.join(unique[i:i + BATCH])}", ext="json",
                                       params={"_format": "json"}))
        return pages

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        items, details = [], {}
        for p in pages:
            data = _loads(p.body)
            if "/api/screenings/date" in p.url:
                items += [(x, p.fetched_at) for x in data]
            else:
                details.update({str(r.get("nid")): r for r in data})
        out = []
        for item, fetched_at in items:
            rec = details.get(str(item.get("nid")))
            start = parse_start(item, self.tz)
            if not rec or not start:
                continue
            films = parse_films(rec)
            title = programme_title(rec, films)
            if not title:
                continue
            single = films[0] if len(films) == 1 else None
            runtimes = [f["runtime_min"] for f in films]
            runtime = sum(runtimes) if films and all(runtimes) else None
            fmts = {f["format"] for f in films if f["format"]}
            fmt = fmts.pop() if len(fmts) == 1 else normalize_format(clean_text(rec.get("media_title_format")))
            if fmt and "|" in fmt:
                fmt = None
            directors = list(dict.fromkeys(f["director"] for f in films if f["director"]))
            start_s = iso(start, self.tz)
            out.append(Screening(
                id=make_id(self.venue.id, start_s, title),
                venue_id=self.venue.id, title=title, start=start_s, day=start.date().isoformat(),
                end=end_from_runtime(start, runtime),
                director=", ".join(directors) if 0 < len(directors) <= 3 else None,
                year=single["year"] if single else None,
                runtime_min=runtime,
                format=fmt or ("Film" if str(rec.get("field_on_film")) in ("true", "1") else None),
                series=_html_text(rec.get("field_series")),
                note=clean_text(item.get("field_note")),
                detail_url=rec.get("field_url") or None,
                source="screenslate",
                scraped_at=fetched_at,
            ))
        return out


def _loads(body: str) -> list:
    body = (body or "").strip()
    if not body:
        return []
    data = json.loads(body)
    return data if isinstance(data, list) else []
