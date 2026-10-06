"""Bryn Mawr Film Institute: week page + programme pages (scraper/sources/brynmawr.py)."""
from datetime import date
from pathlib import Path

from scraper.base import dedupe
from scraper.contract import check_venue, load_fixture
from scraper.registry import build_scraper, load_venues
from scraper.sources.brynmawr import list_dates, parse_time, title_case

FX = Path(__file__).parent / "fixtures" / "bryn-mawr-film-institute"


def rows():
    v = {x.id: x for x in load_venues()}["bryn-mawr-film-institute"]
    return dedupe(build_scraper(v, client=object()).parse(load_fixture(FX).pages))


def test_bryn_mawr_film_institute_contract():
    problems = check_venue("bryn-mawr-film-institute")
    assert not problems, "\n".join(problems)


def test_times_without_am_pm_are_afternoon_and_labels_become_notes():
    assert parse_time("7.30 Open Caption") == (19, 30, "Open caption")
    assert parse_time("1.00 SF") == (13, 0, "Sensory friendly")
    assert parse_time("12.30") == (12, 30, None)
    assert parse_time("11.00am") == (11, 0, None)


def test_list_dates_and_titles():
    ref = date(2026, 10, 6)
    assert list_dates("Oct 6 – 15", ref) == [date(2026, 10, 6), date(2026, 10, 15)]
    assert list_dates("Nov 28 & Dec 12", ref) == [date(2026, 11, 28), date(2026, 12, 12)]
    assert list_dates("Dec 26 & Jan 2", ref) == [date(2026, 12, 26), date(2027, 1, 2)]
    assert title_case("THE HEIRESS with Karina Longworth") == "The Heiress with Karina Longworth"
    assert title_case("National Theatre Live: FLEABAG") == "National Theatre Live: Fleabag"
    assert title_case("Exhibition on Screen – DAVID HOCKNEY AT THE ROYAL ACADEMY OF ARTS") == \
        "Exhibition on Screen – David Hockney at the Royal Academy of Arts"


def test_week_page_and_programme_pages():
    r = rows()
    week = [x for x in r if x.day <= "2026-10-13"]
    later = [x for x in r if x.day > "2026-10-13"]
    assert week and later
    first = week[0]
    assert (first.start, first.title, first.runtime_min) == ("2026-10-06T13:00:00-04:00", "Digger", 128)
    assert first.end == "2026-10-06T15:08:00-04:00"
    oc = next(x for x in week if x.title == "Primetime" and x.start.endswith("T13:00:00-04:00"))
    assert oc.note == "Open caption"
    assert all(x.note == "Subtitled" for x in r if x.title == "Ha-Chan Shake Your Booty!")
    heiress = next(x for x in later if x.title == "The Heiress with Karina Longworth")      # subtitle "On 35mm" dropped
    assert (heiress.start, heiress.director, heiress.year, heiress.format) == \
        ("2026-10-22T19:00:00-04:00", "William Wyler", 1949, "35mm")
    assert heiress.ticket_url.startswith("https://shop.brynmawrfilm.org/websales/pages/ticketsearchcriteria.aspx?evtinfo=")
    social = [x for x in r if x.title == "The Social Reckoning"]
    assert len({x.id for x in social}) == len(social)                                     # week + its page, no doubles
