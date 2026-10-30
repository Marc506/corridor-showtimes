"""Japan Society — WordPress custom events endpoint (SOURCES.md §3)."""
from __future__ import annotations

import json
import re
from datetime import datetime

from bs4 import BeautifulSoup

from ..base import BaseScraper
from ..models import RawPage, Screening
from ..normalize import clean_text, iso, language_from_text, make_id, normalize_format, to_local
from ..registry import register

API = "https://japansociety.org/wp-json/events/v1/data"
POSTS = "https://japansociety.org/wp-json/wp/v2/events"     # the same events' text: the credit line is in it
CATEGORIES = "9127,10825,9194"      # Film, Film Series, Monthly Classics


# "Dir. Noboru Tanaka, 1974, 83 min, DCP, b&w and color, in Japanese with English subtitles. With Meika Seri, …"
CREDIT = re.compile(r"\bDir(?:s)?\.\s+(?P<dir>[^,\n]+(?:,\s*[A-Z][^,\n\d]+?)*?),\s*(?P<year>(?:18|19|20)\d{2}),\s*"
                    r"(?P<min>\d+)\s*min\.?(?P<rest>[^\n]*)")


def parse_detail(html: str) -> dict:
    """An event's text (its page, or the WordPress API's `content`) -> director, year, runtime, format, language
    from the credit line. Without it TMDB guesses from the title alone ("The Oldest Profession" became the 1967
    French anthology, not Noboru Tanaka's 1974 film)."""
    text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    m = CREDIT.search(text)
    if not m:
        return {}
    rest = m.group("rest").split(". With ")[0]
    fmt = next((normalize_format(p) for p in (clean_text(x) for x in rest.split(","))
                if p and re.fullmatch(r"(?:\d+k\s+)?dcp|(?:35|16|70)\s?mm|digital|blu-?ray|vhs", p, re.I)), None)
    return {"director": clean_text(m.group("dir")), "year": int(m.group("year")), "runtime_min": int(m.group("min")),
            "format": fmt, "language": language_from_text(rest)}


def parse_js_datetime(date_s: str, time_s: str, tz=None) -> datetime:
    """'October 7, 2026' + '7:00 pm' -> aware datetime."""
    return to_local(datetime.strptime(f"{date_s.strip()} {time_s.strip().upper()}", "%B %d, %Y %I:%M %p"), tz)


@register("japansociety")
class JapanSocietyScraper(BaseScraper):
    def fetch(self) -> list[RawPage]:
        """The events, then one request for all their texts from the site's WordPress API (the event pages
        themselves answer programs with 403)."""
        events = self.get_page(API, ext="json", params={"events_categories": CATEGORIES})
        ids = [str(e["id"]) for e in json.loads(events.body) if e.get("id")]
        if not ids:
            return [events]
        texts = self.get_page(POSTS, ext="json", params={"include": ",".join(ids[:100]), "per_page": 100,
                                                          "_fields": "id,content"})
        return [events, texts]

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        credits = {}
        for page in pages[1:]:                         # {"id": 79319, "content": {"rendered": "<p>…Dir. …"}}
            for post in json.loads(page.body) if page.body.strip().startswith("[") else []:
                credits[post.get("id")] = parse_detail((post.get("content") or {}).get("rendered") or "")
        out = []
        for page in pages[:1]:
            for ev in json.loads(page.body):
                info = credits.get(ev.get("id")) or {}
                title = clean_text(ev.get("title"))
                days = ev.get("days") or {}
                # multi_day entries without a time are series/exhibition containers: skip.
                if not title or days.get("type") != "single_day":
                    continue
                cats = [c.get("name") for c in (ev.get("terms") or {}).get("events_categories") or []]
                series = next((c for c in cats if c and c not in ("Film", "Film Series")), None)
                for d in days.get("single_day_events") or []:
                    if not d.get("date") or not d.get("time_start"):
                        continue
                    try:
                        start = parse_js_datetime(d["date"], d["time_start"], self.tz)
                    except ValueError:
                        continue
                    end = None
                    if d.get("time_end"):
                        try:
                            end = iso(parse_js_datetime(d["date"], d["time_end"], self.tz), self.tz)
                        except ValueError:
                            pass
                    start_s = iso(start, self.tz)
                    out.append(Screening(
                        id=make_id(self.venue.id, start_s, title),
                        venue_id=self.venue.id,
                        title=title,
                        start=start_s,
                        end=end,
                        day=start.date().isoformat(),
                        series=series,
                        screen="Japan Society",
                        note="Sold out" if ev.get("sold_out") else None,
                        director=info.get("director"), year=info.get("year"), runtime_min=info.get("runtime_min"),
                        format=info.get("format"), language=info.get("language"),
                        detail_url=ev.get("permalink") or None,
                        scraped_at=page.fetched_at,
                    ))
        return out
