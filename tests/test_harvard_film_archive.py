"""Harvard Film Archive: recipe over the calendar pages (scraper/recipes/harvard-film-archive.yaml)."""
from pathlib import Path

from scraper.base import dedupe
from scraper.contract import check_venue, load_fixture
from scraper.registry import build_scraper, load_venues

FX = Path(__file__).parent / "fixtures" / "harvard-film-archive"


def test_harvard_film_archive_contract():
    problems = check_venue("harvard-film-archive")
    assert not problems, "\n".join(problems)


def test_calendar_events():
    v = {x.id: x for x in load_venues()}["harvard-film-archive"]
    rows = dedupe(build_scraper(v, client=object()).parse(load_fixture(FX).pages))
    third = next(r for r in rows if r.title == "The Third Man")
    assert (third.start, third.director, third.year, third.format) == ("2026-10-19T19:00:00-04:00", "Carol Reed", 1949, "35mm")
    assert third.series == "The Cold Heart is More Precious than Diamonds"          # "... " cut off, not shown
    keaton = next(r for r in rows if r.title == "Sherlock Jr.")
    assert keaton.format == "Film" and keaton.note.startswith("Live Musical Accompaniment")
    assert not any(r.series and r.series.endswith(("...", "…")) for r in rows)
