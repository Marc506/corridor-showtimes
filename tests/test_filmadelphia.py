from scraper.sources.filmadelphia import split_title


def test_filmadelphia_feed(parse_fixture):
    rows = parse_fixture("filmadelphia", "feed.json")
    assert len(rows) == 53                               # sum of CurrentShowings in the fixture
    assert all(r.venue_id == "filmadelphia" and r.start[:10] == r.day for r in rows)
    ad = next(r for r in rows if r.title == "American Doctor")
    assert (ad.director, ad.year, ad.runtime_min) == ("Poh Si Teng", 2026, 93)
    assert ad.screen == "PFS - Bourse Theater 3"
    assert ad.series is None                              # "First-Run" is not a series
    assert ad.ticket_url.startswith("https://prod5.agileticketing.net/websales/pages/ticketsearchcriteria.aspx")
    assert ad.end and ad.end > ad.start


def test_filmadelphia_format_and_series(parse_fixture):
    rows = parse_fixture("filmadelphia", "feed.json")
    birth = next(r for r in rows if r.title == "Birth")
    assert (birth.format, birth.series, birth.director) == ("35mm", "Reel October", "Jonathan Glazer")
    gray = next(r for r in rows if r.title == "Ad Astra")
    assert gray.series == "Director Series: JAMES GRAY"


def test_split_title_notes():
    assert split_title("I LOVE BOOSTERS w/ Q&A") == ("I Love Boosters", "w/ Q&A")
    assert split_title("THE WITCH with Introduction by Robert Eggers") == ("The Witch", "with Introduction by Robert Eggers")
    assert split_title("BEAUTY AND THE BEAST") == ("Beauty and the Beast", None)


def test_open_caption_showings_are_tagged():
    import json
    from scraper.models import RawPage
    from tests.conftest import scraper_for
    oc = {"Name": "Amenities", "Group": "Accessibility", "Hidden": True, "Value": "Open Captioning"}
    feed = {"ArrayOfShows": [{"Name": "DIGGER", "Type": "First-Run", "CustomProperties": [], "CurrentShowings": [
        {"StartDate": "2026-10-06T15:30:00", "Venue": {"Name": "PFS - Bourse Theater 1"}, "CustomProperties": [oc]},
        {"StartDate": "2026-10-07T15:30:00", "Venue": {"Name": "PFS - Bourse Theater 1"}, "CustomProperties": []}]}]}
    rows = scraper_for("filmadelphia").parse([RawPage(url="x", body=json.dumps(feed), fetched_at="2026-10-02T01:00:00Z", ext="json")])
    assert [(r.day, r.note) for r in rows] == [("2026-10-06", "Open captions"), ("2026-10-07", None)]
