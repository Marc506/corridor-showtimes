"""Paris Theater (NYC) — the theatre's own schedule, read the way a visitor's browser reads it (SOURCES.md §16).

    source: {adapter: custom, module: paris}

The home page's SCHEDULE strip shows each day's showtimes. The page's own script gets them from the theatre's
ticketing system (Vista): GET https://digital-api.paristheaternyc.com/ocapi/v1/showtimes/by-business-date/<date>
?siteIds=2001, with a short-lived token the page obtains itself. Called directly, that endpoint answers 401 —
so nothing is called directly and no credential is taken from the page: a real (headless) browser opens the
home page like any visitor, presses "Next Date" day by day, and keeps the JSON the page receives. robots.txt
allows the whole site; images, fonts, media and other sites' scripts are not loaded; clicks are a few seconds
apart; a 403 / 429 stops the run and pauses the site (base.Pauses). The ticketing site itself
(tickets.paristheaternyc.com, Cloudflare) is never visited.

Each day's JSON: showtimes {id, schedule {startsAt, filmEndsAt}, filmId, screenId, attributeIds, isSoldOut,
eventId} and relatedData {films {title, runtimeInMinutes, directors}, castAndCrew, attributes ("35MM"), screens,
events}. The ticket link is tickets.paristheaternyc.com/order/showtimes/<id>/seats.

The same home page (Next.js) also embeds its special events weeks ahead in the RSC payload
(`self.__next_f.push([1,"…"])`): {"EventName":"LA BOLA NEGRA | Sneak Preview + Q&A …","EventDate":"2026-10-15",
"EventTime":"7:05 PM","TicketLink":…}, and film records {"FilmName":"A Place in the Sun","Slug":…,
"Director":"George Stevens","Year":"1951"}. An event that matches a showtime (same film, within 10 minutes)
gives it its note; events beyond the days read are added. Film records give the year (Vista's releaseDate is
the US release, wrong for a revival) and the film page.
"""
from __future__ import annotations

import json
import random
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse

from ..base import BaseScraper, BrowserDisabled, Pauses, Refused, browser_disabled
from ..models import RawPage, Screening
from ..normalize import (clean_text, iso, make_id, normalize_format, now_utc_iso, parse_iso, smart_title,
                         title_norm, to_local, today_local)
from ..registry import register

HOME = "https://www.paristheaternyc.com/"
BY_DATE = re.compile(r"/ocapi/v1/showtimes/by-business-date/(\d{4}-\d{2}-\d{2})")
DATES_PATH = "/api/showtime-dates"                    # {"datesByFilm": {film: [dates]}}: which days to read
TICKETS = "https://tickets.paristheaternyc.com/order/showtimes/{id}/seats"
OWN_HOSTS = ("paristheaternyc.com", "moviexchange.com")      # the page's own site and its ticketing login
SKIP_TYPES = {"image", "media", "font"}
MAX_CLICKS = 30
EVENT = re.compile(r'\{"id":(\d+),"attributes":\{"EventName":"((?:[^"\\]|\\.)*)","EventDate":"(\d{4}-\d{2}-\d{2})"'
                   r'(?:(?!"attributes").)*?"TicketLink":"([^"]*)"(?:(?!"attributes").)*?"EventTime":"([^"]*)"', re.S)
TIME = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*([AP]M)$", re.I)
FILM = re.compile(r'"FilmName":"((?:[^"\\]|\\.)*)","Slug":"([^"]*)"')


def rsc_text(html: str) -> str:
    """The Next.js RSC payload of a page, decoded from its self.__next_f.push([1,"…"]) string chunks."""
    out = []
    for chunk in re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', html):
        try:
            out.append(json.loads(f'"{chunk}"'))
        except ValueError:
            continue
    return "".join(out)


def parse_films(text: str) -> dict[str, dict]:
    """title_norm(film name) -> {title, director, year, url} from the film records in the RSC payload."""
    films = {}
    starts = list(FILM.finditer(text))
    for i, m in enumerate(starts):
        seg = text[m.end(): starts[i + 1].start() if i + 1 < len(starts) else m.end() + 4000]
        name = clean_text(json.loads(f'"{m.group(1)}"'))
        director = re.search(r'"Director":"((?:[^"\\]|\\.)*)"', seg)
        year = re.search(r'"Year":"((?:18|19|20)\d{2})"', seg)
        films.setdefault(title_norm(name), {
            "title": name, "url": f"{HOME}film/{m.group(2)}" if m.group(2) else None,
            "director": clean_text(json.loads(f'"{director.group(1)}"')) if director else None,
            "year": int(year.group(1)) if year else None})
    return films


def parse_events(html: str) -> list[dict]:
    """[{title, note, date, hour, minute, ticket_url, director, year, detail_url}] for the special events on
    the home page, completed from the film records."""
    text = rsc_text(html)
    films = parse_films(text)
    events = {}
    for m in EVENT.finditer(text):
        name = json.loads(f'"{m.group(2)}"')
        t = TIME.match(m.group(5).strip())
        if not t:
            continue
        h, mi = int(t.group(1)) % 12 + (12 if t.group(3).upper() == "PM" else 0), int(t.group(2) or 0)
        title, _, note = (clean_text(x) for x in name.partition("|"))
        film = films.get(title_norm(title), {})
        events[m.group(1)] = {"title": film.get("title") or smart_title(title), "note": note or None,
                              "date": m.group(3), "hour": h, "minute": mi, "ticket_url": m.group(4) or None,
                              "director": film.get("director"), "year": film.get("year"),
                              "detail_url": film.get("url") or HOME}
    return list(events.values())


def same_film(a: str, b: str) -> bool:
    x, y = title_norm(a), title_norm(b)
    return bool(x and y) and (x == y or x.startswith(y) or y.startswith(x))


def _text(v) -> str:
    return ((v.get("text") if isinstance(v, dict) else v) or "").strip()


def parse_day(payload: dict) -> list[dict]:
    """One day of Vista showtimes -> [{id, start, end, title, directors, runtime, attributes, screen, sold_out,
    event}] (pure)."""
    rd = payload.get("relatedData") or {}
    films = {f["id"]: f for f in rd.get("films") or [] if "id" in f}

    def person(c):
        n = c.get("name") or {}
        name = " ".join(x.strip() for x in (n.get("givenName"), n.get("middleName"), n.get("familyName")) if x and x.strip())
        return name.title() if name.isupper() else name
    people = {c["id"]: person(c) for c in rd.get("castAndCrew") or [] if "id" in c}
    attrs = {a["id"]: _text(a.get("shortName")) or _text(a.get("name")) for a in rd.get("attributes") or [] if "id" in a}
    screens = {x["id"]: _text(x.get("name")) for x in rd.get("screens") or [] if "id" in x}
    events = {e["id"]: _text(e.get("name")) or _text(e.get("title")) for e in rd.get("events") or [] if "id" in e}
    out = []
    for st in payload.get("showtimes") or []:
        film = films.get(st.get("filmId"), {})
        ids = [d.get("castAndCrewMemberId") for d in film.get("directors") or []]
        sched = st.get("schedule") or {}
        if not sched.get("startsAt"):
            continue
        out.append({"id": st.get("id"), "start": sched["startsAt"], "end": sched.get("filmEndsAt") or sched.get("endsAt"),
                    "title": _text(film.get("title")), "directors": [people[i] for i in ids if i in people],
                    "runtime": film.get("runtimeInMinutes"),
                    "attributes": [attrs[a] for a in st.get("attributeIds") or [] if attrs.get(a)],
                    "screen": screens.get(st.get("screenId")), "sold_out": bool(st.get("isSoldOut")),
                    "event": events.get(st.get("eventId")) if st.get("eventId") else None})
    return out


@register("paris")
class ParisScraper(BaseScraper):
    needs_browser = True

    def fetch(self) -> list[RawPage]:
        """Open the home page in a headless browser and press "Next Date" until the last day with showings within
        horizon_days; keep the day JSON the page receives, and the page itself (special events, film records)."""
        if browser_disabled():
            raise BrowserDisabled("browser disabled (CINEMA_NO_BROWSER=1)")
        if until := Pauses.until(HOME):
            raise Refused(f"{HOME} refused us earlier; paused until {until}")
        from playwright.sync_api import sync_playwright
        last = (today_local(self.tz) + timedelta(days=self.venue.horizon_days)).isoformat()
        days: dict[str, str] = {}
        dates: set[str] = set()
        refused: list[tuple[str, int]] = []

        def route(r):
            req = r.request
            host = urlparse(req.url).hostname or ""
            if req.resource_type in SKIP_TYPES or not host.endswith(OWN_HOSTS):
                return r.abort()
            return r.continue_()

        def seen(resp):
            if resp.status in (403, 429):
                refused.append((resp.url, resp.status))
            elif resp.status == 200:
                try:
                    if m := BY_DATE.search(resp.url):
                        days[m.group(1)] = resp.text()
                    elif urlparse(resp.url).path == DATES_PATH:
                        for ds in (resp.json().get("datesByFilm") or {}).values():
                            dates.update(ds)
                except Exception:  # noqa: BLE001 — a body that isn't text/JSON is not ours to read
                    pass

        wait = max(self.venue.rate_limit_s, 2.5)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                ctx = browser.new_context(locale="en-US", timezone_id=self.venue.timezone)
                ctx.route("**/*", route)
                page = ctx.new_page()
                page.on("response", seen)
                page.goto(HOME, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(int(wait * 1000))
                home = page.content()
                target = max((d for d in dates if d <= last), default=last)
                nxt, stale = page.locator('button[aria-label="Next Date"]'), 0
                for _ in range(MAX_CLICKS):
                    if refused or (days and max(days) >= target) or not nxt.count() or not nxt.first.is_enabled():
                        break
                    before = len(days)
                    nxt.first.click()
                    page.wait_for_timeout(int((wait + random.uniform(0, 2)) * 1000))
                    stale = stale + 1 if len(days) == before else 0
                    if stale >= 4:
                        break
            finally:
                browser.close()
        if refused:
            Pauses.refused(*refused[0])
            raise Refused(f"HTTP {refused[0][1]}: {refused[0][0]}")
        now = now_utc_iso()
        return ([RawPage(url=f"{HOME}#showtimes/{d}", body=body, fetched_at=now, ext="json") for d, body in sorted(days.items())]
                + [RawPage(url=HOME, body=home, fetched_at=now, ext="html")])

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        home = [p for p in pages if p.ext == "html"]
        films = {}
        for page in home:
            films.update(parse_films(rsc_text(page.body)))
        rows: dict[str, Screening] = {}
        for page in (p for p in pages if p.ext == "json"):
            for x in parse_day(json.loads(page.body)):
                start = parse_iso(x["start"], self.tz)
                title = smart_title(clean_text(x["title"])) or x["title"]
                rec = films.get(title_norm(title), {})
                fmts = [normalize_format(a) for a in x["attributes"] if re.fullmatch(r"\d+\s?mm|dcp|4k|70mm", a, re.I)]
                notes = [a for a in x["attributes"] if not re.fullmatch(r"\d+\s?mm|dcp|4k|70mm", a, re.I)]
                notes += [x["event"]] if x["event"] else []
                notes += ["Sold out"] if x["sold_out"] else []
                end = parse_iso(x["end"], self.tz) if x["end"] else None
                start_s = iso(start, self.tz)
                rows[x["id"]] = Screening(
                    id=make_id(self.venue.id, start_s, title), venue_id=self.venue.id, title=rec.get("title") or title,
                    start=start_s, day=start.date().isoformat(), end=iso(end, self.tz) if end and end > start else None,
                    director=", ".join(x["directors"]) or rec.get("director"), year=rec.get("year"),
                    runtime_min=x["runtime"] or None, format=fmts[0] if fmts else None, screen=x["screen"],
                    note="; ".join(notes) or None, detail_url=rec.get("url") or HOME,
                    ticket_url=TICKETS.format(id=x["id"]), scraped_at=page.fetched_at)
        out = list(rows.values())
        for page in home:                               # special events: notes for showtimes, or added beyond them
            for e in parse_events(page.body):
                d = datetime.fromisoformat(e["date"])
                start = to_local(d.replace(hour=e["hour"], minute=e["minute"]), self.tz)
                twin = next((r for r in out if abs(parse_iso(r.start, self.tz) - start) <= timedelta(minutes=10)
                             and same_film(r.title, e["title"])), None)
                if twin:
                    twin.note = "; ".join(dict.fromkeys(n for n in (e["note"], twin.note) if n)) or None
                    continue
                start_s = iso(start, self.tz)
                out.append(Screening(
                    id=make_id(self.venue.id, start_s, e["title"]), venue_id=self.venue.id, title=e["title"],
                    start=start_s, day=start_s[:10], note=e["note"], detail_url=e["detail_url"],
                    director=e["director"], year=e["year"], ticket_url=e["ticket_url"], scraped_at=page.fetched_at))
        return out
