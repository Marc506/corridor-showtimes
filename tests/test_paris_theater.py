"""Paris Theater: the day JSON its home page receives, plus the special events on that page (scraper/sources/paris.py)."""
from pathlib import Path

from scraper.base import dedupe
from scraper.contract import check_venue, load_fixture
from scraper.models import RawPage
from scraper.registry import build_scraper, load_venues

FX = Path(__file__).parent / "fixtures" / "paris-theater"


def scraper():
    return build_scraper({x.id: x for x in load_venues()}["paris-theater"], client=object())


def test_paris_theater_contract():
    problems = check_venue("paris-theater")
    assert not problems, "\n".join(problems)


def test_regular_showtimes_come_from_the_day_json():
    r = dedupe(scraper().parse(load_fixture(FX).pages))
    bola = [x for x in r if x.title == "La Bola Negra" and x.start >= "2026-11-03"]
    assert bola and all(x.format == "35mm" and x.screen == "Screen 1" and x.runtime_min == 160 for x in bola)
    assert {x.director for x in bola} == {"Javier Ambrossi, Javier Calvo"}               # as the ticketing data lists them
    assert all(x.ticket_url.startswith("https://tickets.paristheaternyc.com/order/showtimes/2001-") for x in r)
    burning = next(x for x in r if x.title == "Burning")
    assert (burning.year, burning.detail_url) == (2018, "https://www.paristheaternyc.com/film/burning-paris")  # film record


def test_special_events_from_the_home_page():
    """Events on the home page add their note to the matching showtime, or are added beyond the days read."""
    home = RawPage(url="https://www.paristheaternyc.com/", fetched_at="2026-10-07T14:00:00Z", ext="html",
                   body=(FX.parent / "paris_home_2026-10-07.html").read_text())
    r = scraper().parse([home])
    sun = next(x for x in r if x.title == "A Place in the Sun")   # event name "A PLACE IN THE SUN | …"
    assert (sun.start, sun.director, sun.year, sun.note) == \
        ("2026-10-31T12:00:00-04:00", "George Stevens", 1951, "Introduced by Karina Longworth")
    assert sun.detail_url == "https://www.paristheaternyc.com/film/a-place-in-the-sun-paris"
    bola = [x for x in r if x.title == "La Bola Negra"]           # not "LA Bola Negra"
    assert len(bola) == 3 and all(x.note for x in bola)
