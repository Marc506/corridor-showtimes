"""Somerville Theatre: the TAPOS XML feed behind the site's schedule (scraper/sources/tapos.py)."""
from pathlib import Path

from scraper.base import dedupe
from scraper.contract import check_venue, load_fixture
from scraper.registry import build_scraper, load_venues
from scraper.sources.tapos import production_url

FX = Path(__file__).parent / "fixtures" / "somerville-theatre"


def rows():
    v = {x.id: x for x in load_venues()}["somerville-theatre"]
    return dedupe(build_scraper(v, client=object()).parse(load_fixture(FX).pages))


def test_somerville_theatre_contract():
    problems = check_venue("somerville-theatre")
    assert not problems, "\n".join(problems)


def test_feed():
    r = rows()
    aliens = next(x for x in r if x.title == "Aliens")                        # FilmTitle "Aliens 70mm"
    assert (aliens.start, aliens.format, aliens.runtime_min, aliens.screen, aliens.imdb_id) == \
        ("2026-11-18T19:00:00-05:00", "70mm", 137, "Main Theatre", "tt0090605")
    assert aliens.detail_url == "https://www.somervilletheatre.com/production/aliens-70mm/"
    assert aliens.ticket_url.startswith("https://internet-ticketing.com/websales/sales/CSBSOM/book?perfcode=")
    assert not any(x.director for x in r)                       # the feed's Directors field is not trusted
    assert any(x.note == "Open captions" for x in r)
    assert {x.screen for x in r} <= {"Main Theatre", "Screen 2", "Screen 3", "Screen 4", "Screen 5"}
    assert not any(x.title.lower().endswith(("35mm", "70mm", "4k")) for x in r)


def test_production_url_matches_the_sites_own_slug():
    assert production_url("https://x.org", "Warren Miller's Days Off") == "https://x.org/production/warren-millers-days-off/"
    assert production_url("https://x.org", "I Can Do Hard Things: Samantha's Story") == \
        "https://x.org/production/i-can-do-hard-things-samanthas-story/"
