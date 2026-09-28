import json

from scraper.models import RawPage
from scraper.registry import build_scraper, load_venues
from scraper.sources.japansociety import parse_js_datetime


def test_japansociety_fixture(parse_fixture):
    rows = parse_fixture("japansociety", "events.json")
    assert len(rows) == 1
    r = rows[0]
    assert r.title == "Hirayasumi Anime – Exclusive Early Look at Episode 1"
    assert r.start == "2026-10-07T19:00:00-04:00"
    assert r.day == "2026-10-07"
    assert r.screen == "Japan Society"
    assert r.detail_url.startswith("https://japansociety.org/events/")


def test_japansociety_skips_multiday_containers_and_parses_lowercase_pm():
    venue = next(v for v in load_venues() if v.id == "japansociety")
    events = [
        {"id": 1, "title": "Naruse Retrospective", "permalink": "https://x/1",
         "days": {"type": "multi_day", "single_day_events": None,
                  "milti_day_events": {"date_start": "October 6, 2026", "date_end": "December 15, 2026",
                                       "time_start": "", "time_end": ""}}},
        {"id": 2, "title": "Floating Clouds", "permalink": "https://x/2", "sold_out": True,
         "days": {"type": "single_day", "single_day_events": [
             {"date": "November 3, 2026", "time_start": "7:00 pm", "time_end": ""},
             {"date": "November 8, 2026", "time_start": "2:30 PM", "time_end": ""}]}},
    ]
    page = RawPage(url="x", body=json.dumps(events), fetched_at="2026-09-25T01:00:00Z", ext="json")
    rows = build_scraper(venue, client=object()).parse([page])
    assert [(r.title, r.start) for r in rows] == [
        ("Floating Clouds", "2026-11-03T19:00:00-05:00"),   # after DST ends
        ("Floating Clouds", "2026-11-08T14:30:00-05:00"),
    ]
    assert rows[0].note == "Sold out"


def test_parse_js_datetime():
    assert parse_js_datetime("October 7, 2026", "7:00 pm").isoformat() == "2026-10-07T19:00:00-04:00"
