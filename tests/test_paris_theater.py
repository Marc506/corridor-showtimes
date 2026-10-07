"""Paris Theater: screenslate plus the special events on the theatre's home page (scraper/sources/paris.py)."""
from pathlib import Path

from scraper.base import dedupe
from scraper.contract import check_venue, load_fixture
from scraper.registry import build_scraper, load_venues

FX = Path(__file__).parent / "fixtures" / "paris-theater"


def rows():
    v = {x.id: x for x in load_venues()}["paris-theater"]
    return dedupe(build_scraper(v, client=object()).parse(load_fixture(FX).pages))


def test_paris_theater_contract():
    problems = check_venue("paris-theater")
    assert not problems, "\n".join(problems)


def test_special_events_from_the_home_page():
    r = rows()
    assert all(x.source == "primary" for x in r)                  # screenslate is this venue's own source
    sun = next(x for x in r if x.title == "A Place in the Sun")   # event name "A PLACE IN THE SUN | …"
    assert (sun.start, sun.director, sun.year, sun.note) == \
        ("2026-10-31T12:00:00-04:00", "George Stevens", 1951, "Introduced by Karina Longworth")
    assert sun.detail_url == "https://www.paristheaternyc.com/film/a-place-in-the-sun-paris"
    assert sun.ticket_url.startswith("https://tickets.paristheaternyc.com/order/showtimes/")
    bola = [x for x in r if x.title == "La Bola Negra"]           # not "LA Bola Negra"
    assert len(bola) == 3 and all(x.note for x in bola)
    assert any(x.title == "The Deer Hunter" for x in r)           # screenslate's schedule
