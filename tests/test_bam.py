from scraper.base import dedupe


def test_bam_parses_films_only(parse_fixture):
    rows = parse_fixture("bam", "calendar.json")
    assert len(rows) > 100
    assert all(r.venue_id == "bam" and r.source == "primary" for r in rows)
    titles = {r.title for r in rows}
    assert "Tony" in titles
    assert "Così fan tutte" in titles          # "Opera,Film" composite genre is kept
    # every row is a real, offset-bearing local datetime whose date matches `day`
    for r in rows:
        assert r.start[:10] == r.day and r.start[-6:] in ("-04:00", "-05:00")


def test_bam_expands_performances_and_links(parse_fixture):
    rows = [r for r in parse_fixture("bam", "calendar.json") if r.title == "Tony"]
    assert rows[0].start == "2026-09-24T21:20:00-04:00"
    assert rows[0].detail_url == "https://www.bam.org/film/2026/tony"
    assert rows[0].ticket_url == "https://commerce.bam.org/production/58217"
    assert len({r.start for r in rows}) == len(rows) > 1


def test_bam_titles_are_trimmed_and_ids_stable(parse_fixture):
    rows = parse_fixture("bam", "calendar.json")
    assert all(r.title == r.title.strip() for r in rows)
    assert [r.id for r in dedupe(rows)] == [r.id for r in dedupe(parse_fixture("bam", "calendar.json"))]
    opera = next(r for r in rows if r.title == "Macbeth")
    assert opera.note == "Live Broadcast, Opera"


def test_bam_detail_page():
    from scraper.sources.bam import parse_detail
    from tests.conftest import FIXTURES
    d = parse_detail((FIXTURES / "bam" / "detail_tony.html").read_text())
    assert d == {"director": "Matt Johnson", "year": 2026, "runtime_min": 106, "format": "DCP"}
