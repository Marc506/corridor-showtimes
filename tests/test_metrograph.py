from datetime import date

from scraper.sources.metrograph import _note_for_day, parse_metadata


def test_metrograph_page(parse_fixture):
    rows = parse_fixture("metrograph", "nyc.html")
    assert len(rows) == 164
    ht = next(r for r in rows if r.title == "Happy Together")
    assert (ht.director, ht.year, ht.runtime_min, ht.format) == ("Wong Kar-wai", 1997, 96, "DCP")
    assert ht.detail_url == "https://metrograph.com/film/?vista_film_id=9999000497"
    assert "txtSessionId=" in ht.ticket_url
    assert ht.end is not None


def test_metrograph_sold_out_and_dated_notes(parse_fixture):
    rows = parse_fixture("metrograph", "nyc.html")
    ed = next(r for r in rows if r.title == "Eddington" and r.day == "2026-09-26")
    assert ed.note == "Q&A with director Ari Aster and cinematographer Darius Khondji; Sold out"
    tokyo = {r.day: r.note for r in rows if r.title == "Tokyo Melody"}
    assert tokyo["2026-09-26"] == "Introduction by composer Paul Grimstad"
    assert tokyo["2026-09-28"] is None       # intro was only on the 26th


def test_parse_metadata_missing_fields():
    assert parse_metadata("/ 1991 / 105min / DCP") == {"director": None, "year": 1991, "runtime_min": 105, "format": "DCP"}
    assert parse_metadata("Aki  Kaurismäki / 1990 / 79min / DCP")["director"] == "Aki Kaurismäki"
    assert parse_metadata("Tsui Hark / 1984 / 103min / 4K DCP")["format"] == "4K DCP"


def test_note_for_day_undated_applies_everywhere():
    assert _note_for_day("U.S. premiere", date(2026, 9, 29)) == "U.S. premiere"
