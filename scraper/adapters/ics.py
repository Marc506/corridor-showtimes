"""iCalendar feeds (PLATFORMS.md §9).

    source: {adapter: ics, url: "https://uniondocs.org/events/?ical=1", categories: ["Screenings & Events"]}

Timed VEVENTs only (all-day and multi-day entries are exhibitions or workshops). DTSTART with a TZID
is converted to the venue's zone; floating times are taken as venue-local.
"""
from __future__ import annotations

from datetime import date, datetime

from ..base import BaseScraper, ScrapeError
from ..models import RawPage, Screening
from ..normalize import clean_text, iso, make_id, to_local
from . import Candidate, register_adapter

MAX_SPAN_H = 8


def _calendar(body: str):
    from icalendar import Calendar
    try:
        return Calendar.from_ical(body)
    except ValueError:
        return None


def _categories(comp) -> set[str]:
    raw = comp.get("categories")
    items = raw if isinstance(raw, list) else [raw] if raw is not None else []
    out = set()
    for c in items:
        cats = getattr(c, "cats", None)
        out |= {str(x) for x in cats} if cats is not None else {str(c)}
    return out


@register_adapter("ics")
class IcsAdapter(BaseScraper):
    PARAMS = {"url": str}
    OPTIONAL_PARAMS = {"categories": list}
    DETECT_ORDER = 70

    def fetch(self) -> list[RawPage]:
        url = self.params["url"].replace("webcal://", "https://")
        page = self.get_page(url, ext="ics")
        if "BEGIN:VCALENDAR" not in page.body[:2000]:
            raise ScrapeError("calendar URL did not return an iCalendar file")
        return [page]

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        wanted = set(self.params.get("categories") or [])
        out = []
        for page in pages:
            cal = _calendar(page.body)
            if cal is None:
                continue
            for ev in cal.walk("VEVENT"):
                if wanted and not _categories(ev) & wanted:
                    continue
                start = ev.decoded("dtstart", None)
                if not isinstance(start, datetime):
                    continue                                  # all-day
                end = ev.decoded("dtend", None)
                start = to_local(start, self.tz)
                end = to_local(end, self.tz) if isinstance(end, datetime) else None
                if end and (end - start).total_seconds() > MAX_SPAN_H * 3600:
                    continue
                title = clean_text(str(ev.get("summary") or ""))
                if not title:
                    continue
                start_s = iso(start, self.tz)
                out.append(Screening(
                    id=make_id(self.venue.id, start_s, title), venue_id=self.venue.id, title=title,
                    start=start_s, day=start.date().isoformat(),
                    end=iso(end, self.tz) if end and end > start else None,
                    detail_url=str(ev.get("url")) if ev.get("url") else None, scraped_at=page.fetched_at))
        return out

    @classmethod
    def detect(cls, probe) -> Candidate | None:
        urls = probe.findall(r'<link[^>]+type=["\']text/calendar["\'][^>]+href=["\']([^"\']+)')
        urls += [u for u in probe.links() if u.lower().endswith(".ics") or u.startswith("webcal://") or "ical=1" in u]
        for u in list(dict.fromkeys(urls))[:2]:
            r = probe.get(u.replace("webcal://", "https://").replace("&#038;", "&"))
            if not r or r.status != 200 or "BEGIN:VCALENDAR" not in r.text[:2000]:
                continue
            cal = _calendar(r.text)
            timed = [e for e in cal.walk("VEVENT") if isinstance(e.decoded("dtstart", None), datetime)] if cal else []
            if timed:
                return Candidate("ics", {"url": r.url}, [f"iCalendar feed {r.url} with {len(timed)} timed events"],
                                 order=cls.DETECT_ORDER)
        return None
