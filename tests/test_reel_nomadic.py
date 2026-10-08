"""Reel Nomadic: contract test on tests/fixtures/reel-nomadic/ (written by python -m scraper.add)."""
from scraper.contract import check_venue


def test_reel_nomadic_contract():
    problems = check_venue("reel-nomadic")
    assert not problems, "\n".join(problems)


def test_reel_nomadic_titles_are_the_films_of_the_night(parse_fixture):
    """ma.to names the evening; the films are quoted in its description."""
    rows = parse_fixture("reel-nomadic", ("page_0.html", "https://ma.to/venue/reel_nomadic"))
    assert [(r.start, r.title, r.series, r.screen) for r in rows] == [
        ("2026-10-09T18:00:00-04:00", "Young Frankenstein + The Lost Boys", "Halloween Fest – Friday", "Penn Treaty Park"),
        ("2026-10-10T15:00:00-04:00", "Ghostbusters + They Live", "Halloween Fest – Saturday", "Penn Treaty Park")]
    assert rows[0].note.startswith("Outdoor screenings of 'Young Frankenstein'")
    assert rows[0].detail_url == "https://ma.to/event/halloween-fest-friday-2026-10-09"


def test_quoted_titles_keep_apostrophes():
    from scraper.adapters.jsonld import QUOTED
    assert QUOTED.findall("Screenings of 'Schindler's List' and ‘They Live’ tonight") == ["Schindler's List", "They Live"]
    assert QUOTED.findall("Free screening of Coraline in the wine garden.") == []
