"""ICA Boston: recipe over the film calendar (scraper/recipes/ica-boston.yaml)."""
from pathlib import Path

from scraper.base import dedupe
from scraper.contract import check_venue, load_fixture
from scraper.registry import build_scraper, load_venues

FX = Path(__file__).parent / "fixtures" / "ica-boston"


def test_ica_boston_contract():
    problems = check_venue("ica-boston")
    assert not problems, "\n".join(problems)


def test_film_calendar():
    v = {x.id: x for x in load_venues()}["ica-boston"]
    rows = dedupe(build_scraper(v, client=object()).parse(load_fixture(FX).pages))
    tcb = next(r for r in rows if r.title.startswith("TCB"))
    assert tcb.start == "2026-10-09T19:00:00-04:00"                     # "Fri, Oct 9, 7 PM", year from the fetch date
    assert tcb.detail_url == "https://www.icaboston.org/events/tcb-the-toni-cade-bambara-school-of-organizing/"
