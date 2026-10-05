"""Landmark Ritz Five: contract test on tests/fixtures/landmark-ritz-five/ (written by python -m scraper.add)."""
from scraper.contract import check_venue


def test_landmark_ritz_five_contract():
    problems = check_venue("landmark-ritz-five")
    assert not problems, "\n".join(problems)
