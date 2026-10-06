"""County Theater and Ambler Theater: the same Renew Theaters template as the Hiway (scraper/sources/renew.py)."""
import pytest

from scraper.contract import check_venue


@pytest.mark.parametrize("venue_id", ["county-theater", "ambler-theater"])
def test_renew_theater_contract(venue_id):
    problems = check_venue(venue_id)
    assert not problems, "\n".join(problems)
