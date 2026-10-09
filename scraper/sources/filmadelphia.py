"""Philadelphia Film Society — Agile Ticketing's public event feed (SOURCES.md §9).

filmadelphia.org itself sits behind a WAF that blocks every non-browser client, but their ticketing
provider publishes an official JSON feed. The parsing lives in the generic `agile` adapter; this module
only pins PFS's entry-point GUID and cluster so existing venues.yaml entries (`scraper: filmadelphia`,
`agile_guid:`) keep working. New Agile venues use `source: {adapter: agile, guid: …, host: …}` directly.

The Philadelphia Film Festival is sold through another entry point that this feed doesn't cover. Its printed
schedule grid, turned into `config/schedules/<name>.yaml` by scripts/import_pff_grid.py, is listed in the
venue's `schedules:`; a row from it is dropped when the feed lists the same film in the same building (Bourse /
East / Center) within 10 minutes, so the feed's own row — with its ticket link — wins once it appears. (Time and
building alone are not enough: the Bourse's first-run films run beside the festival in its other rooms.)
"""
from __future__ import annotations

from datetime import datetime, timedelta

import yaml

from ..adapters.agile import AgileAdapter, props, split_title  # noqa: F401  (re-exported for callers/tests)
from ..base import ROOT
from ..models import RawPage, Screening
from ..normalize import end_from_runtime, iso, make_id, now_utc_iso, parse_iso, smart_title, title_norm, to_local
from ..registry import register

FESTIVAL_PAGE = "https://filmadelphia.org/festival/films/"


def building(screen: str | None) -> str | None:
    """'PFS - Bourse Theater 3' / 'Film Society Bourse 3' -> 'bourse'; 'PFC - Greenfield' / 'Film Society Center' -> 'center'."""
    s = (screen or "").lower()
    return next((b for b, keys in (("bourse", ("bourse",)), ("east", ("east",)), ("center", ("pfc", "center")))
                 if any(k in s for k in keys)), None)

EVENTS_GUID = "6634566a-a49f-4dec-89e6-bb4c5eda4814"      # "Philadelphia Film Society - EVENTS" entry point
HOST = "prod5.agileticketing.net"


@register("filmadelphia")
class FilmadelphiaScraper(AgileAdapter):
    enforce_budget = False

    def __init__(self, venue, client=None, params=None):
        super().__init__(venue, client=client, params=params)
        self.schedules = list(venue.extra.get("schedules") or [])
        self.params = {"guid": self.params.get("guid") or venue.extra.get("agile_guid") or EVENTS_GUID,
                       "host": self.params.get("host") or HOST}

    def fetch(self) -> list[RawPage]:
        pages = super().fetch()
        for rel in self.schedules:
            pages.append(RawPage(url=f"file://{ROOT / rel}", body=(ROOT / rel).read_text(encoding="utf-8"),
                                 fetched_at=now_utc_iso(), ext="yaml"))
        return pages

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        feed = super().parse([p for p in pages if p.ext != "yaml"])
        taken = [(building(s.screen), parse_iso(s.start, self.tz), title_norm(s.title)) for s in feed]
        extra = []
        for page in (p for p in pages if p.ext == "yaml"):
            for s in self.schedule_rows(page):
                b, t, n = building(s.screen), parse_iso(s.start, self.tz), title_norm(s.title)
                if not any(b == tb and abs(t - tt) <= timedelta(minutes=10) and (n in tn or tn in n)
                           for tb, tt, tn in taken):
                    extra.append(s)
        return feed + extra

    def schedule_rows(self, page: RawPage) -> list[Screening]:
        data = yaml.safe_load(page.body) or {}
        out = []
        for row in data.get("screenings") or []:
            start = to_local(datetime.fromisoformat(str(row["start"])), self.tz)
            title = smart_title(row["title"])
            start_s = iso(start, self.tz)
            out.append(Screening(
                id=make_id(self.venue.id, start_s, title), venue_id=self.venue.id, title=title, start=start_s,
                day=start.date().isoformat(), end=end_from_runtime(start, row.get("runtime_min"), self.tz),
                runtime_min=row.get("runtime_min"), series=data.get("series"), screen=row.get("screen"),
                note=row.get("section"), detail_url=FESTIVAL_PAGE, scraped_at=page.fetched_at))
        return out
