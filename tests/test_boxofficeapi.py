"""Webedia box-office API adapter (Landmark Theatres): field mapping, offline."""
import json

from scraper.adapters.boxofficeapi import movie_facts, slug
from scraper.models import RawPage
from tests.conftest import scraper_for


def test_movie_facts():
    m = {"id": "631", "title": "The Mummy (1932)", "release": "1932-12-22T00:00:00.000Z", "runtime": 4380,
         "directors": {"nodes": [{"person": {"firstName": "Karl", "lastName": "Freund"}}]}, "coDirectors": {"nodes": []}}
    assert movie_facts(m) == {"title": "The Mummy", "director": "Karl Freund", "year": 1932, "runtime": 73}
    assert movie_facts({"title": "Untimed", "runtime": None})["runtime"] is None
    assert slug("The Mummy (1932)") == "the-mummy-1932"


def test_schedule_mapping():
    sched = {"X081D": {"schedule": {"631": {"2026-10-07": [
        {"startsAt": "2026-10-07T19:00:00", "tags": ["Format.Projection.35mm", "Showtime.Accessibility.Subtitled"],
         "screen": {"name": "2"}, "data": {"ticketing": [{"provider": "relay", "urls": ["https://relay/x"]},
                                                          {"provider": "default", "urls": ["https://booking/y"]}]}}]}}}}
    movies = [{"id": "631", "title": "The Mummy (1932)", "release": "1932-12-22", "runtime": 4380,
               "directors": {"nodes": []}}]
    pages = [RawPage(url="https://www.landmarktheatres.com/api/gatsby-source-boxofficeapi/schedule?x=1",
                     body=json.dumps(sched), fetched_at="2026-10-05T12:00:00Z", ext="json"),
             RawPage(url="https://www.landmarktheatres.com/api/gatsby-source-boxofficeapi/movies?ids=631",
                     body=json.dumps(movies), fetched_at="2026-10-05T12:00:00Z", ext="json")]
    r = scraper_for("landmark-ritz-five").parse(pages)[0]
    assert (r.title, r.start, r.end) == ("The Mummy", "2026-10-07T19:00:00-04:00", "2026-10-07T20:13:00-04:00")
    assert (r.format, r.note, r.screen) == ("35mm", "Subtitled", "Screen 2")
    assert r.ticket_url == "https://booking/y"
    assert r.detail_url == "https://www.landmarktheatres.com/movies/631-the-mummy-1932/"
