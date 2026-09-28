"""Philadelphia Film Society — Agile Ticketing's public event feed (SOURCES.md §9).

filmadelphia.org itself sits behind a WAF that blocks every non-browser client, but their ticketing
provider publishes an official JSON feed. The parsing lives in the generic `agile` adapter; this module
only pins PFS's entry-point GUID and cluster so existing venues.yaml entries (`scraper: filmadelphia`,
`agile_guid:`) keep working. New Agile venues use `source: {adapter: agile, guid: …, host: …}` directly.
"""
from __future__ import annotations

from ..adapters.agile import AgileAdapter, props, split_title  # noqa: F401  (re-exported for callers/tests)
from ..registry import register

EVENTS_GUID = "6634566a-a49f-4dec-89e6-bb4c5eda4814"      # "Philadelphia Film Society - EVENTS" entry point
HOST = "prod5.agileticketing.net"


@register("filmadelphia")
class FilmadelphiaScraper(AgileAdapter):
    enforce_budget = False

    def __init__(self, venue, client=None, params=None):
        super().__init__(venue, client=client, params=params)
        self.params = {"guid": self.params.get("guid") or venue.extra.get("agile_guid") or EVENTS_GUID,
                       "host": self.params.get("host") or HOST}
