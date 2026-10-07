"""Screening contract (scraper/contract.py) for every venue that has a fixture manifest.

    pytest tests/test_contract.py -k <venue_id>

Venues come from config/venues.yaml (fixtures in tests/fixtures/<id>/fixture.yaml) and from
tests/fixtures/platforms/venues.yaml, the demo venues that exercise each platform adapter against
real pages (their `fixture:` key points into tests/fixtures/platforms/<adapter>/).
"""
from pathlib import Path

import pytest

from scraper.base import dedupe
from scraper.config import load_venues
from scraper.contract import check, has_fixture, load_fixture
from scraper.registry import VENUES_FILE, build_scraper

FIXTURES = Path(__file__).parent / "fixtures"
PLATFORM_VENUES = FIXTURES / "platforms" / "venues.yaml"


def _cases():
    cases = []
    for v in load_venues(VENUES_FILE):
        if has_fixture(FIXTURES / v.id):
            cases.append(pytest.param(v, FIXTURES / v.id, None, id=v.id))
    if PLATFORM_VENUES.exists():
        for v in load_venues(PLATFORM_VENUES):
            cases.append(pytest.param(v, PLATFORM_VENUES.parent, v.extra["fixture"], id=v.id))
    return cases


@pytest.mark.parametrize("venue,directory,manifest", _cases())
def test_contract(venue, directory, manifest):
    fx = load_fixture(directory, manifest)
    scraper = build_scraper(venue, client=object())
    rows = dedupe(scraper.parse(fx.pages))
    again = dedupe(scraper.parse(fx.pages))
    problems = check(venue, rows, fx.fetched_date, again)
    assert not problems, "\n".join(problems)


def test_every_enabled_venue_has_a_fixture():
    # reference chains are never shown; their adapter is covered by tests/fixtures/platforms (alamo)
    missing = [v.id for v in load_venues(VENUES_FILE) if v.enabled and not v.reference and not has_fixture(FIXTURES / v.id)]
    assert not missing, f"no tests/fixtures/<id>/fixture.yaml for: {missing}"
