"""Brattle Theatre: contract test on tests/fixtures/brattle-theatre/ (written by python -m scraper.add)."""
from scraper.contract import check_venue


def test_brattle_theatre_contract():
    problems = check_venue("brattle-theatre")
    assert not problems, "\n".join(problems)
