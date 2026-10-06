"""Renew Theaters' cinema sites (the Hiway Theater, Jenkintown) — server-rendered PHP (SOURCES.md §12).

    source: {adapter: custom, module: renew, base_url: https://www.hiwaytheater.org}

Two pages share one markup: the home page ("Now Playing": this week's main attractions, plus a few
specials) and /specials (every special programme, months ahead). One block per programme:

    <div id="box-times">
      <div class="details"><div class="year">1981</div><div class="format">35mm</div></div>
      <div class="header"><span class="tag-bar cult">Cult Cinema Club</span>
        <div class="subheader">A Christmas Carol (1951)</div>
        <a href="films/halloween-ii" class="title">Halloween II</a>
        <div class="date-container" data-date="Fri Oct 23">          (home page: data-date="Tue 6")
          <ul class="session-times"><li><a href="https://tickets…/checkout/showing/halloween-ii/3821020">
            9:45 PM <span class="screen-attribute">OC</span></a></li></ul>

Main attractions' times have no am/pm ("7:00"); specials mostly do ("10:00 AM"). An unmarked time follows
Film Forum's rule: 11 is morning, 12 noon, 1–10 afternoon or evening. "OC" = open captions. Showtimes are
set a week at a time, so the home page holds everything there is for main attractions.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..base import BaseScraper
from ..models import RawPage, Screening
from ..normalize import clean_text, iso, make_id, nearest_date, normalize_format, to_local
from ..registry import register

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
WEEKDAYS = {d: i for i, d in enumerate(["mon", "tue", "wed", "thu", "fri", "sat", "sun"])}
TIME = re.compile(r"^(\d{1,2}):(\d{2})\s*(AM|PM)?$", re.I)
ATTRIBUTES = {"oc": "Open caption"}
NOT_SERIES = re.compile(r"^(ends|starts|opens|held over|last|now|final)\b", re.I)


def show_date(label: str, ref: date) -> date | None:
    """'Sat Oct 10' -> that date nearest the fetch day; 'Tue 6' -> the day-6 that is a Tuesday near it."""
    parts = (clean_text(label) or "").split()
    if len(parts) == 3 and parts[1][:3].lower() in MONTHS and parts[2].isdigit():
        return nearest_date(MONTHS[parts[1][:3].lower()], int(parts[2]), ref)
    if len(parts) == 2 and parts[0][:3].lower() in WEEKDAYS and parts[1].isdigit():
        wd, dom = WEEKDAYS[parts[0][:3].lower()], int(parts[1])
        for k in range(-7, 60):
            d = ref + timedelta(days=k)
            if d.day == dom and d.weekday() == wd:
                return d
    return None


def show_time(text: str) -> tuple[int, int] | None:
    m = TIME.match(clean_text(text) or "")
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2)), (m.group(3) or "").upper()
    if ap == "AM":
        h = 0 if h == 12 else h
    elif ap == "PM" or 1 <= h <= 10:
        h = h if h == 12 else h + 12
    return h, mi                                   # unmarked 11 stays morning, 12 noon


@register("renew")
class RenewScraper(BaseScraper):
    @property
    def base(self) -> str:
        return (self.params.get("base_url") or self.venue.website or "").rstrip("/")

    def fetch(self) -> list[RawPage]:
        return [self.get_page(self.base + "/"), self.get_page(self.base + "/specials")]

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        out = []
        for page in pages:
            ref = to_local(datetime.fromisoformat(page.fetched_at.replace("Z", "+00:00")), self.tz).date()
            soup = BeautifulSoup(page.body, "lxml")
            for box in soup.select("div#box-times"):
                link = box.select_one("a.title")
                if not link:
                    continue
                for hidden in link.select("span"):
                    hidden.decompose()
                title = clean_text(link.get_text(" "))
                detail = urljoin(page.url, link.get("href") or "")
                year_s = clean_text(box.select_one(".details .year").get_text()) if box.select_one(".details .year") else ""
                fmt = box.select_one(".details .format")
                tags = [clean_text(t.get_text(" ")) for t in box.select(".tag-bar")]
                series = next((t for t in tags if t and not NOT_SERIES.match(t)), None)
                sub = box.select_one(".subheader")
                subheader = clean_text(sub.get_text(" ")) if sub else None
                for day_box in box.select(".date-container"):
                    day = show_date(day_box.get("data-date") or day_box.get_text(" "), ref)
                    if not day or not title:
                        continue
                    for a in day_box.select("ul.session-times li a, ul.session-times li span"):
                        attrs = [clean_text(x.get_text()) for x in a.select(".screen-attribute")]
                        for x in a.select(".screen-attribute"):
                            x.decompose()
                        hm = show_time(a.get_text(" "))
                        if not hm:
                            continue
                        start = to_local(datetime(day.year, day.month, day.day, *hm), self.tz)
                        start_s = iso(start, self.tz)
                        notes = [ATTRIBUTES.get(x.lower(), x) for x in attrs if x] + ([subheader] if subheader else [])
                        out.append(Screening(
                            id=make_id(self.venue.id, start_s, title), venue_id=self.venue.id, title=title,
                            start=start_s, day=start_s[:10],
                            year=int(year_s) if re.fullmatch(r"(18|19|20)\d{2}", year_s) else None,
                            format=normalize_format(clean_text(fmt.get_text())) if fmt else None,
                            series=series, note="; ".join(notes) or None, detail_url=detail,
                            ticket_url=a.get("href") or detail, scraped_at=page.fetched_at))
        return out
