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


def test_reel_nomadic_has_no_made_up_end(parse_fixture):
    """ma.to's endDate 23:59 means "rest of the day", not when the films end."""
    rows = parse_fixture("reel-nomadic", ("page_0.html", "https://ma.to/venue/reel_nomadic"))
    assert [r.end for r in rows] == [None, None]


def test_event_page_gives_doors_and_film_start(monkeypatch):
    from scraper.adapters.jsonld import event_timing
    from scraper.models import Screening
    from tests.conftest import FIXTURES, scraper_for
    html = (FIXTURES / "reel-nomadic" / "event_friday.html").read_text()
    assert event_timing(html) == {"doors": (18, 0), "opens": "Doors", "films_when": "after dark"}
    stated = html.replace("Films begin after dark", "Films begin at 7:30 p.m.")
    assert event_timing(stated) == {"doors": (18, 0), "opens": "Doors", "films_at": (19, 30)}
    saturday = html.replace("Doors at 6 p.m.", "Starts at 3 p.m.").replace("after dark", "at sundown")
    assert event_timing(saturday) == {"doors": (15, 0), "opens": "Starts", "films_when": "at sundown"}

    scraper = scraper_for("reel-nomadic")
    row = lambda: Screening(id="x", venue_id="reel-nomadic", title="Young Frankenstein + The Lost Boys",  # noqa: E731
                            start="2026-10-09T18:00:00-04:00", day="2026-10-09", detail_url="https://ma.to/event/x")
    for page, start, note in [(html, "2026-10-09T18:00:00-04:00", "Doors 6pm; films begin after dark"),
                              (stated, "2026-10-09T19:30:00-04:00", "Doors 6pm; films begin 7:30pm")]:
        monkeypatch.setattr(scraper, "detail_info", lambda url, parse, ttl=None, page=page: parse(page))
        rows = [row()]
        scraper.enrich(rows)
        assert (rows[0].start, rows[0].note) == (start, note)
