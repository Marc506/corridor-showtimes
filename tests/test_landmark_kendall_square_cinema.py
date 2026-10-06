"""Landmark Kendall Square Cinema: contract test on tests/fixtures/landmark-kendall-square-cinema/ (written by python -m scraper.add)."""
from scraper.contract import check_venue


def test_landmark_kendall_square_cinema_contract():
    problems = check_venue("landmark-kendall-square-cinema")
    assert not problems, "\n".join(problems)
