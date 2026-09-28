"""Film Forum — /now_playing, 7 day tabs, times without am/pm (SOURCES.md §5)."""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

from bs4 import BeautifulSoup, Comment

from ..base import BaseScraper, ref_date
from ..models import RawPage, Screening
from ..normalize import clean_text, iso, make_id, smart_title, to_local
from ..registry import register

URL = "https://filmforum.org/now_playing"


def infer_time(hhmm: str) -> time:
    """Film Forum prints '12:50', '7:00'. 11 -> am, 12 -> noon, 1–10 -> pm. No shows before 11am."""
    h, m = (int(x) for x in hhmm.strip().split(":"))
    if h == 11 or h == 12:
        return time(h, m)
    if 1 <= h <= 10:
        return time(h + 12, m)
    raise ValueError(f"unexpected Film Forum time {hhmm!r}")


def infer_date(day_of_month: int, ref: date) -> date:
    """Pick the date with this day-of-month closest to `ref` (handles month/year roll-over)."""
    candidates = []
    for delta in (-1, 0, 1):
        y, m = ref.year, ref.month + delta
        if m == 0:
            y, m = y - 1, 12
        elif m == 13:
            y, m = y + 1, 1
        try:
            candidates.append(date(y, m, day_of_month))
        except ValueError:
            pass
    return min(candidates, key=lambda d: abs((d - ref).days))


def parse_detail(html: str) -> dict:
    """Detail page: 'Japan, 1964 / Directed by Masaki Kobayashi / … / Approx. 183 min.'"""
    text = BeautifulSoup(html, "lxml").get_text("\n", strip=True)
    start = text.find("SHOWTIMES & TICKETS")
    text = text[start:] if start >= 0 else text
    out: dict = {}
    m = re.search(r"Directed by ([^\n]+)", text, re.I)
    if m:
        out["director"] = smart_title(clean_text(m.group(1)).rstrip(".")) 
    m = re.search(r"^[^\n]{0,80}?,?\s*\b((?:19|20)\d{2})$", text, re.M)
    if m:
        out["year"] = int(m.group(1))
    m = re.search(r"(?:Approx\.\s*)?\b(\d{2,3})\s*min\b", text)
    if m:
        out["runtime_min"] = int(m.group(1))
    return out


def unify_titles(venue_id: str, rows: list[Screening]) -> list[Screening]:
    """The same film is sometimes printed truncated ('…') on one day and in full/short on another;
    use one title per detail URL, preferring an untruncated one."""
    by_url: dict[str, list[str]] = {}
    for r in rows:
        if r.detail_url:
            by_url.setdefault(r.detail_url, []).append(r.title)
    best = {}
    for url, titles in by_url.items():
        full = [t for t in titles if not t.endswith("…")] or titles
        best[url] = max(set(full), key=lambda t: (full.count(t), -len(t)))
    for r in rows:
        if r.detail_url and r.title != best[r.detail_url]:
            r.title = best[r.detail_url]
            r.id = make_id(venue_id, r.start, r.title)
    return rows


@register("filmforum")
class FilmForumScraper(BaseScraper):
    def fetch(self) -> list[RawPage]:
        return [self.get_page(URL)]

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        out = []
        for page in pages:
            ref = ref_date(page)
            soup = BeautifulSoup(page.body, "lxml")
            prev: date | None = None
            for tab in soup.select('div[id^="tabs-"]'):
                c = tab.find(string=lambda x: isinstance(x, Comment))
                m = re.search(r"\d{1,2}", c or "")
                if not m:
                    continue
                day = infer_date(int(m.group()), prev + timedelta(days=1) if prev else ref)
                prev = day
                for p in tab.find_all("p"):
                    a = p.select_one("strong a")
                    if not a:
                        continue
                    title = smart_title(clean_text(a.get_text(" ")))
                    alert = p.select_one("span.alert")
                    note = clean_text(alert.get_text(" ")) if alert else None
                    for span in p.find_all("span"):
                        if "alert" in (span.get("class") or []):
                            continue
                        txt = (span.get_text() or "").strip()
                        if not re.fullmatch(r"\d{1,2}:\d{2}", txt):
                            continue
                        start = to_local(datetime.combine(day, infer_time(txt)))
                        start_s = iso(start)
                        out.append(Screening(
                            id=make_id(self.venue.id, start_s, title),
                            venue_id=self.venue.id, title=title, start=start_s,
                            day=day.isoformat(), note=note,
                            detail_url=a.get("href") or None,
                            ticket_url=a.get("href") or None,
                            scraped_at=page.fetched_at,
                        ))
        return unify_titles(self.venue.id, out)

    def enrich(self, screenings: list[Screening]) -> None:
        self.enrich_by_url(screenings, parse_detail)
