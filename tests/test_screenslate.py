import json
from datetime import datetime, timezone

from scraper.sources.screenslate import parse_films, parse_start, programme_title
from scraper.sources.screenslate import ScreenslateScraper
from tests.conftest import FIXTURES, page, scraper_for


def rows(_parse_fixture=None):
    """Screenslate fixtures live in their own folder but stand in for MoMA."""
    urls = json.loads((FIXTURES / "screenslate" / "urls.json").read_text())
    pages = [page("screenslate", name, url) for name, url in urls.items()]
    return ScreenslateScraper(scraper_for("moma").venue, client=object()).parse(pages)


def test_screenslate_rows_are_marked_and_timed(parse_fixture):
    rs = rows(parse_fixture)
    assert len(rs) > 10
    assert all(r.source == "screenslate" and r.venue_id == "moma" for r in rs)
    assert all(r.start[:10] == r.day and r.start[-6:] == "-04:00" for r in rs)


def test_screenslate_display_title_and_shorts_programme(parse_fixture):
    rs = rows(parse_fixture)
    titles = {r.title for r in rs}
    assert "New York No Story" in titles                         # field_display_title wins
    lnw = next(r for r in rs if r.title.startswith("Song for Rent") and r.start == "2026-10-03T16:00:00-04:00")
    assert lnw.title == "Song for Rent + Dangling Participle + 6 more"
    assert lnw.format == "16mm" and lnw.note == "Q&A with the curator"
    assert lnw.runtime_min and lnw.end                           # summed runtime -> end time
    assert lnw.director is None                                  # >3 directors: omitted


def test_screenslate_single_film_fields(parse_fixture):
    r = next(r for r in rows(parse_fixture) if r.title == "Ip Man 4: The Finale")
    assert (r.director, r.year, r.runtime_min, r.format) == ("Wilson Yip", 2019, 107, "DCP")
    assert r.series and "Yuen Woo-ping" in r.series
    assert r.detail_url.startswith("https://www.moma.org/calendar/")


def test_parse_start_formats():
    assert parse_start({"field_timestamp": "2026-09-26T12:15:00"}).isoformat() == "2026-09-26T12:15:00-04:00"
    ts = int(datetime(2026, 9, 26, 16, 15, tzinfo=timezone.utc).timestamp())      # = 12:15 in New York
    assert parse_start({"field_timestamp": str(ts)}).isoformat() == "2026-09-26T12:15:00-04:00"
    assert parse_start({"field_timestamp": ""}) is None


def test_programme_title_fallbacks():
    two = {"media_title_labels": "<span>A</span>|<span>B</span>", "media_title_info": ""}
    assert programme_title(two, parse_films(two)) == "A + B"
    none = {"title": "Toney W. Merritt PGM 3 at AFA", "media_title_labels": ""}
    assert programme_title(none, []) == "Toney W. Merritt PGM 3"
