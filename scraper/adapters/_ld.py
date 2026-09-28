"""schema.org Event / ScreeningEvent -> Screening, shared by the veezi and jsonld adapters (PLATFORMS.md §8)."""
from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import urljoin

from ..models import Screening
from ..normalize import (clean_text, end_from_runtime, iso, iso_duration_minutes, make_id, smart_title,
                         split_format_suffix, to_local)
from ..probe import jsonld_objects, ld_types

EVENT_TYPES = {"Event", "ScreeningEvent", "VisualArtsEvent", "TheaterEvent", "Festival", "SocialEvent",
               "EducationEvent", "ComedyEvent", "MusicEvent", "LiteraryEvent"}
CANCELLED = ("EventCancelled", "EventPostponed")
# "Tony - Mon, Sep 28 at 9PM", "Creepshow - 10/2/26 @ 7:00 pm": the showtime repeated in the name
NAME_WHEN = re.compile(r"\s+[-–—]\s+[^-–—]*\b\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?\s*$", re.I)


def events(html: str) -> list[dict]:
    """Event-typed JSON-LD objects whose startDate carries a time (Film Forum's are empty strings).
    A workPresented given as {"@id": …} is replaced by the object with that @id, when the page has it."""
    objs = jsonld_objects(html)
    by_id = {o["@id"]: o for o in objs if isinstance(o.get("@id"), str) and len(o) > 2}
    out = []
    for o in objs:
        if not (ld_types(o) & EVENT_TYPES) or parse_start(o.get("startDate")) is None:
            continue
        work = o.get("workPresented")
        if isinstance(work, dict) and set(work) == {"@id"} and work["@id"] in by_id:
            o = {**o, "workPresented": by_id[work["@id"]]}
        out.append(o)
    return out


def parse_start(value) -> datetime | None:
    s = str(value or "").strip()
    if len(s) < 16 or "T" not in s:            # date-only events have no showtime
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _name(v) -> str | None:
    if isinstance(v, list):
        names = [_name(x) for x in v]
        return ", ".join(n for n in names if n) or None
    if isinstance(v, dict):
        return clean_text(v.get("name"))
    return clean_text(v) if isinstance(v, str) else None


def _offer_url(offers) -> str | None:
    for o in offers if isinstance(offers, list) else [offers]:
        if isinstance(o, dict) and o.get("url"):
            return o["url"]
    return None


def to_screening(obj: dict, venue_id: str, tz, page_url: str, fetched_at: str,
                 ticket_hint: str | None = None) -> Screening | None:
    """ticket_hint: substring marking obj.url as a purchase link (e.g. "/purchase/"), else it's a detail page."""
    if any(s in str(obj.get("eventStatus") or "") for s in CANCELLED):
        return None
    work = obj.get("workPresented") if isinstance(obj.get("workPresented"), dict) else {}
    title = clean_text(work.get("name")) or NAME_WHEN.sub("", clean_text(obj.get("name")) or "") or None
    start = parse_start(obj.get("startDate"))
    if not title or start is None:
        return None
    title, fmt = split_format_suffix(title)
    title = smart_title(title)
    start = to_local(start, tz)
    runtime = iso_duration_minutes(obj.get("duration")) or iso_duration_minutes(work.get("duration"))
    runtime = runtime if runtime and runtime <= 600 else None
    end = None
    if (e := parse_start(obj.get("endDate"))) and 0 < (to_local(e, tz) - start).total_seconds() <= 8 * 3600:
        end = iso(e, tz)
    url = urljoin(page_url, obj["url"]) if isinstance(obj.get("url"), str) and obj["url"] else None
    ticket = _offer_url(obj.get("offers"))
    if url and ticket_hint and ticket_hint in url:
        ticket, url = ticket or url, None
    year = None
    if isinstance(work.get("dateCreated"), str) and work["dateCreated"][:4].isdigit():
        year = int(work["dateCreated"][:4])
    start_s = iso(start, tz)
    return Screening(
        id=make_id(venue_id, start_s, title), venue_id=venue_id, title=title, start=start_s,
        day=start.date().isoformat(), end=end or end_from_runtime(start, runtime),
        director=_name(work.get("director")) or _name(obj.get("director")), year=year, runtime_min=runtime,
        format=fmt, detail_url=url, ticket_url=urljoin(page_url, ticket) if ticket else None,
        scraped_at=fetched_at)


def fetched_date(fetched_at: str, tz) -> date:
    return datetime.fromisoformat(fetched_at.replace("Z", "+00:00")).astimezone(tz).date()
