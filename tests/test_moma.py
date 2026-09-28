"""MoMA parser against a SYNTHETIC fixture (markup from SOURCES.md §8; live page blocked by Cloudflare)."""
from datetime import date

from scraper.sources.moma import infer_day, parse_listing, parse_time, series_links
from tests.conftest import FIXTURES

HTML = (FIXTURES / "moma" / "synthetic_series.html").read_text()


def test_moma_listing():
    rows = parse_listing(HTML, date(2025, 12, 20))
    assert [(r["title"], r["start"].isoformat()) for r in rows] == [
        ("BLKNWS: Terms & Conditions", "2025-12-30T19:00:00-05:00"),
        ("Wing Chun", "2025-12-30T16:00:00-05:00"),
        ("Blues + Breakfast (Table Top Dolly)", "2026-01-02T11:30:00-05:00"),   # year roll-over
    ]
    first = rows[0]
    assert (first["year"], first["director"]) == (2025, "Kahlil Joseph")
    assert first["note"] == "Introduced by cinematographer Bradford Young"
    assert first["screen"] == "MoMA, Floor T2/T1"
    assert first["series"].startswith("Yuen Woo-ping")
    assert rows[2]["year"] is None                      # multi-film: no single year


def test_moma_index_page_has_no_series():
    assert parse_listing(HTML, date(2025, 12, 20), h1_is_series=False)[0]["series"] is None


def test_moma_helpers():
    assert parse_time("7:00\xa0p.m.") == (19, 0)
    assert parse_time("11:30 a.m.") == (11, 30)
    assert parse_time("12 p.m.") == (12, 0)
    assert infer_day("Jan", 2, date(2025, 12, 20)) == date(2026, 1, 2)
    assert infer_day("Sep", 20, date(2026, 9, 24)) == date(2026, 9, 20)
    assert series_links('<a href="/calendar/film/5930?locale=en">x</a><a href="/calendar/film">y</a>') == [
        "https://www.moma.org/calendar/film/5930"]
