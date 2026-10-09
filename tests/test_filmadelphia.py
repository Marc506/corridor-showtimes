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


def test_festival_schedule_fills_in_what_the_feed_lacks(parse_fixture):
    """Rows from config/schedules/*.yaml (the festival's printed grid) join the feed's; the feed's own listing of
    the same film in the same building wins, but a different film next door is not mistaken for it."""
    from scraper.models import RawPage
    from tests.conftest import page, scraper_for
    feed = parse_fixture("filmadelphia", "feed.json")
    ad = next(r for r in feed if r.title == "American Doctor")
    t = ad.start[:16]
    grid = f"""series: Philadelphia Film Festival
screenings:
- {{start: '{t}', screen: Film Society Bourse 1, title: AMERICAN DOCTOR, runtime_min: 93, section: Non/Fiction}}
- {{start: '{t}', screen: Film Society Bourse 2, title: THE LAST CRITIC, runtime_min: 83, section: Sight & Soundtrack}}
- {{start: '2026-10-15T18:45', screen: Film Society Center, title: THE ONLY LIVING PICKPOCKET IN N.Y., runtime_min: 88}}
"""
    yml = RawPage(url="file://config/schedules/x.yaml", body=grid, fetched_at=ad.scraped_at, ext="yaml")
    rows = scraper_for("filmadelphia").parse([page("filmadelphia", "feed.json"), yml])
    added = [r for r in rows if r.series == "Philadelphia Film Festival"]
    assert len(rows) == len(feed) + 2
    assert [(r.title, r.note) for r in added] == [("The Last Critic", "Sight & Soundtrack"),
                                                  ("The Only Living Pickpocket in N.Y.", None)]
    pick = added[1]
    assert (pick.start, pick.end, pick.screen) == ("2026-10-15T18:45:00-04:00", "2026-10-15T20:13:00-04:00",
                                                   "Film Society Center")
    assert pick.detail_url == "https://filmadelphia.org/festival/films/"
