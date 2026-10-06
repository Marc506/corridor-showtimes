"""Hiway Theater (Renew Theaters' site template, scraper/sources/renew.py)."""
from datetime import date
from pathlib import Path

from scraper.base import dedupe
from scraper.contract import check_venue, load_fixture
from scraper.registry import build_scraper, load_venues
from scraper.sources.renew import show_date, show_time

FX = Path(__file__).parent / "fixtures" / "hiway-theater"


def test_hiway_theater_contract():
    problems = check_venue("hiway-theater")
    assert not problems, "\n".join(problems)


def test_dates_and_times_without_am_pm():
    ref = date(2026, 10, 6)
    assert show_date("Tue 6", ref) == date(2026, 10, 6)
    assert show_date("Thu 8", ref) == date(2026, 10, 8)
    assert show_date("Sat Dec 19", ref) == date(2026, 12, 19)
    assert show_time("7:00") == (19, 0) and show_time("6:30") == (18, 30)
    assert show_time("10:00 AM") == (10, 0) and show_time("9:45 PM") == (21, 45)
    assert show_time("11:00") == (11, 0) and show_time("12:15") == (12, 15)


def test_home_page_and_specials():
    v = {x.id: x for x in load_venues()}["hiway-theater"]
    rows = dedupe(build_scraper(v, client=object()).parse(load_fixture(FX).pages))
    assert any(r.note and "Open caption" in r.note for r in rows)
    h2 = next(r for r in rows if r.title == "Halloween II")
    assert (h2.start, h2.year, h2.format, h2.series) == ("2026-10-23T21:45:00-04:00", 1981, "35mm", "Horror at the Hiway")
    assert h2.ticket_url.startswith("http") and "/checkout/showing/halloween-ii/" in h2.ticket_url
    assert len({r.id for r in rows}) == len(rows)
