import json

from scraper.models import RawPage
from tests.conftest import scraper_for


def test_placeholder_values_are_unknown():
    feed = {"ArrayOfShows": [{"Name": "SURPRISE 35! PFS MEMBER EDITION", "Type": "REEL OCTOBER", "Duration": "585",
            "CustomProperties": [{"Name": "Director", "Value": "?"}, {"Name": "Original Language", "Value": "?"},
                                 {"Name": "Run Time", "Value": "585"}, {"Name": "Format", "Value": "35MM"}],
            "CurrentShowings": [{"StartDate": "2026-10-03T12:00:00", "EndDate": "2026-10-03T21:45:00", "Venue": {"Name": "PFC - Mainstage"}}]}]}
    page = RawPage(url="x", body=json.dumps(feed), fetched_at="2026-09-25T01:00:00Z", ext="json")
    r = scraper_for("filmadelphia").parse([page])[0]
    assert (r.director, r.language, r.runtime_min, r.format, r.end) == (None, None, None, "35mm", None)
