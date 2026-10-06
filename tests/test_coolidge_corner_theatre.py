"""Coolidge Corner Theatre: recipe over one page per day (scraper/recipes/coolidge-corner-theatre.yaml)."""
from pathlib import Path

from scraper.base import dedupe
from scraper.contract import check_venue, load_fixture
from scraper.registry import build_scraper, load_venues

FX = Path(__file__).parent / "fixtures" / "coolidge-corner-theatre"


def rows():
    v = {x.id: x for x in load_venues()}["coolidge-corner-theatre"]
    return dedupe(build_scraper(v, client=object()).parse(load_fixture(FX).pages))


def test_coolidge_corner_theatre_contract():
    problems = check_venue("coolidge-corner-theatre")
    assert not problems, "\n".join(problems)


def test_day_pages():
    r = rows()
    assert not any("Voting Counts" in x.title or x.title.startswith("Seminar:") for x in r)   # classes, not screenings
    mystery = next(x for x in r if x.title == "Mystery Train")
    assert (mystery.start, mystery.format, mystery.series) == ("2026-10-08T19:00:00-04:00", "35mm", "Cinema Jukebox®")
    assert mystery.screen.startswith("MH")
    assert mystery.ticket_url.startswith("https://store.coolidge.org/websales/pages/ticketsearchcriteria.aspx?evtinfo=")
    assert mystery.detail_url == "https://coolidge.org/films/mystery-train"
    salem = next(x for x in r if x.title.endswith("Aboard the Sea Witch"))
    assert salem.screen is None and salem.series == "After Midnite"       # off-site: placed by venues.yaml `places`
