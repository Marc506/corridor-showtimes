"""Lightbox Film Center: contract test on tests/fixtures/lightbox-film-center/ (written by python -m scraper.add)."""
from scraper.contract import check_venue


def test_lightbox_film_center_contract():
    problems = check_venue("lightbox-film-center")
    assert not problems, "\n".join(problems)
