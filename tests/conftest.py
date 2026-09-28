from pathlib import Path

import pytest

from scraper.models import RawPage, VenueConfig
from scraper.registry import build_scraper, load_venues

FIXTURES = Path(__file__).parent / "fixtures"
FETCHED_AT = "2026-09-25T01:00:00Z"          # = 2026-09-24 21:00 in New York


def page(venue_id: str, name: str, url: str | None = None) -> RawPage:
    path = FIXTURES / venue_id / name
    return RawPage(url=url or f"file://{path}", body=path.read_text(encoding="utf-8"),
                   fetched_at=FETCHED_AT, ext="json" if name.endswith(".json") else "html")


def scraper_for(venue_id: str, venue: VenueConfig | None = None):
    venues = {v.id: v for v in load_venues()}
    return build_scraper(venue or venues[venue_id], client=object())


@pytest.fixture
def parse_fixture():
    """parse_fixture("bam", "calendar.json") -> list[Screening], fully offline.
    Pass (name, url) tuples for sources whose parse() reads the page URL."""
    def _parse(venue_id: str, *names, venue: VenueConfig | None = None):
        pages = [page(venue_id, *n) if isinstance(n, tuple) else page(venue_id, n) for n in names]
        return scraper_for(venue_id, venue).parse(pages)
    return _parse
