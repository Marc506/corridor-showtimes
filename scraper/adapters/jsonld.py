"""Generic schema.org Event / ScreeningEvent reader (PLATFORMS.md §8).

    source:
      adapter: jsonld
      pages: [https://brattlefilm.org/]                # pages whose JSON-LD lists showtimes
      follow: "a[href*='/movies/']"                     # optional: also read pages linked from them (one hop)
      max_follow: 15

Only events whose startDate carries a time count — Film Forum's home page lists ScreeningEvents with
empty dates, which must not be mistaken for a schedule. Usually a small site's fallback or a quick
detection signal; a platform adapter is preferred when one matches.
"""
from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..base import BaseScraper, RequestBudgetExceeded
from ..models import RawPage, Screening
from . import Candidate, register_adapter
from ._ld import events, to_screening


@register_adapter("jsonld")
class JsonLdAdapter(BaseScraper):
    PARAMS = {"pages": list}
    OPTIONAL_PARAMS = {"follow": str, "max_follow": int, "ticket_hint": str}
    DETECT_ORDER = 80

    def fetch(self) -> list[RawPage]:
        pages = [self.get_page(u) for u in self.params["pages"]]
        sel = self.params.get("follow")
        if sel:
            seen = set(self.params["pages"])
            links = []
            for p in pages:
                for a in BeautifulSoup(p.body, "lxml").select(sel):
                    if a.get("href"):
                        u = urljoin(p.url, a["href"]).split("#")[0]
                        if u not in seen:
                            seen.add(u)
                            links.append(u)
            for u in links[: int(self.params.get("max_follow", 15))]:
                try:
                    pages.append(self.get_page(u))
                except RequestBudgetExceeded:
                    break
        return pages

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        hint = self.params.get("ticket_hint", "/purchase/")
        return [s for p in pages for o in events(p.body)
                if (s := to_screening(o, self.venue.id, self.tz, p.url, p.fetched_at, ticket_hint=hint))]

    @classmethod
    def detect(cls, probe) -> Candidate | None:
        found = [(r.final_url or r.url, len(events(r.text))) for r in probe.pages]
        found = [(u, n) for u, n in found if n]
        if not found:
            return None
        return Candidate("jsonld", {"pages": [u for u, _ in found]},
                         [f"{n} schema.org events with showtimes on {u}" for u, n in found], order=cls.DETECT_ORDER)
