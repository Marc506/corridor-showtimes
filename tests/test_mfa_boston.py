"""MFA Boston: recipe over the film programme page (scraper/recipes/mfa-boston.yaml)."""
from pathlib import Path

from scraper.base import dedupe
from scraper.contract import check_venue, load_fixture
from scraper.registry import build_scraper, load_venues

FX = Path(__file__).parent / "fixtures" / "mfa-boston"


def test_mfa_boston_contract():
    problems = check_venue("mfa-boston")
    assert not problems, "\n".join(problems)


def test_only_the_start_of_a_time_range_is_a_showtime():
    v = {x.id: x for x in load_venues()}["mfa-boston"]
    rows = dedupe(build_scraper(v, client=object()).parse(load_fixture(FX).pages))
    assert len({r.detail_url for r in rows}) == len(rows)          # "7:00 pm–8:45 pm" is one screening
    siege = next(r for r in rows if r.title == "Chronicles from the Siege")
    assert siege.start == "2026-10-23T19:00:00-04:00" and siege.ticket_url.startswith("https://tnew.mfa.org/")
    assert any(r.note == "Sold Out" for r in rows)
