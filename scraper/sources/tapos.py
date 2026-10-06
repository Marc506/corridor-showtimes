"""TAPOS ticketing feed served by the cinema's own WordPress site (Somerville Theatre, SOURCES.md §15).

    source: {adapter: custom, module: tapos, feed: "https://www.somervilletheatre.com/wp-admin/admin-ajax.php?action=tapos_feed"}

The site's schedule page builds itself from this one public XML document (every film, every performance,
months ahead), so one GET per run reads the whole programme:

    <Film><Code>163</Code><FilmTitle>Aliens 70mm</FilmTitle><ShortFilmTitle>Aliens</ShortFilmTitle>
          <RunningTime>137</RunningTime><IMDBCode>tt0090605</IMDBCode><Directors>James Cameron</Directors>…
    <Performance><FilmCode>163</FilmCode><PerformDate>2026-11-18</PerformDate><StartTime>19:00:00</StartTime>
          <Screen>Main Theatre - Somerville</Screen><PerfFlagsDescription>70mm</PerfFlagsDescription>
          <BookingURL>https://internet-ticketing.com/websales/sales/CSBSOM/book?perfcode=1186</BookingURL>…

ShortFilmTitle is cut at 20 characters, so the title is FilmTitle without a trailing print format ("Aliens
70mm" -> "Aliens", format 70mm). The feed's Directors field is not used: it mixes in wrong names ("The Blues
Brothers: Derek Drymon|John Landis"); the IMDb id gives TMDB the exact film instead (language.by_imdb).
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import quote, urlparse

from ..base import BaseScraper, ScrapeError
from ..models import RawPage, Screening
from ..normalize import clean_text, end_from_runtime, iso, make_id, normalize_format, to_local
from ..registry import register

FORMAT_SUFFIX = re.compile(r"\s+(35\s*mm|70\s*mm|16\s*mm|4k)$", re.I)
FLAGS = {"35mm": ("format", "35mm"), "70mm": ("format", "70mm"), "16mm": ("format", "16mm"), "4k": ("format", "4K"),
         "open captions": ("note", "Open captions")}


def text(node, tag: str) -> str:
    v = clean_text(node.findtext(tag) or "") or ""
    return "" if v in ("None", "none") else v


def production_url(site: str, film_title: str) -> str:
    """The site's own film page, built the way its schedule script does: /production/<slug>/."""
    slug = re.sub(r"[\W_]+", "-", film_title.replace("'", ""))
    return f"{site}/production/{quote(slug).lower()}/"


@register("tapos")
class TaposScraper(BaseScraper):
    def fetch(self) -> list[RawPage]:
        return [self.get_page(self.params["feed"], ext="xml")]

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        out = []
        for page in pages:
            try:
                root = ET.fromstring(page.body.encode("utf-8"))
            except ET.ParseError as e:
                raise ScrapeError(f"TAPOS feed is not XML: {e}") from None
            site = "{0.scheme}://{0.netloc}".format(urlparse(page.url))
            films = {}
            for f in root.iter("Film"):
                full = text(f, "FilmTitle") or text(f, "ShortFilmTitle")
                m = FORMAT_SUFFIX.search(full)
                title = full[:m.start()] if m else full
                rt = text(f, "RunningTime")
                imdb = text(f, "IMDBCode")
                films[text(f, "Code")] = {
                    "title": title, "page": production_url(site, full),
                    "runtime": int(rt) if rt.isdigit() and 1 <= int(rt) <= 600 else None,
                    "imdb": imdb if re.fullmatch(r"tt\d{5,10}", imdb) else None,
                    "format": normalize_format(m.group(1).replace(" ", "").upper().replace("MM", "mm")) if m else None,
                }
            for p in root.iter("Performance"):
                film = films.get(text(p, "FilmCode"))
                if not film or "Y" in (text(p, "PerformancesHidden"), text(p, "Virtual")):
                    continue
                try:
                    start = to_local(datetime.fromisoformat(f"{text(p, 'PerformDate')}T{text(p, 'StartTime')}"), self.tz)
                except ValueError:
                    continue
                fmt, notes = film["format"], []
                for flag in re.split(r"\s*[,|]\s*", text(p, "PerfFlagsDescription")):
                    kind, value = FLAGS.get(flag.lower(), ("note", flag) if flag else (None, None))
                    if kind == "format":
                        fmt = fmt or value
                    elif kind == "note":
                        notes.append(value)
                if text(p, "SoldOutLevel") not in ("", "N"):
                    notes.append("Sold out")
                start_s = iso(start, self.tz)
                out.append(Screening(
                    id=make_id(self.venue.id, start_s, film["title"]), venue_id=self.venue.id, title=film["title"],
                    start=start_s, day=start_s[:10], end=end_from_runtime(start, film["runtime"], self.tz),
                    runtime_min=film["runtime"], format=fmt, note="; ".join(dict.fromkeys(notes)) or None,
                    screen=re.sub(r"\s*-\s*Somerville$", "", text(p, "Screen")) or None,
                    detail_url=film["page"], ticket_url=text(p, "BookingURL") or film["page"],
                    imdb_id=film["imdb"], scraped_at=page.fetched_at))
        return out
