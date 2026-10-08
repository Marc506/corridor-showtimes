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



def test_bam_day_programme_splits_into_its_film_blocks():
    """A one-day programme whose page lists a running order becomes one row per film block; talks are left out.
    One or two films keep their titles; a set of three or more takes the programme's name, without the presenter.
    A talk with the film's director right after it joins that row."""
    from scraper.models import Screening
    from scraper.sources.bam import parse_detail, split_programme
    from tests.conftest import FIXTURES
    d = parse_detail((FIXTURES / "bam" / "detail_bwfc.html").read_text())
    parent = Screening(id="x", venue_id="bam", title="New Negress Film Society presents Black Women's Film Conference 2026",
                       start="2026-10-10T12:01:00-04:00", day="2026-10-10", detail_url="https://www.bam.org/film/x")
    rows = split_programme(parent, d["schedule"], "America/New_York")
    conf = "Black Women's Film Conference 2026"
    assert [(r.start[11:16], r.end[11:16], r.title) for r in rows] == [     # each runs through its own talk
        ("12:15", "13:45", conf), ("13:45", "15:45", conf), ("16:30", "19:00", "Sugar Island"),
        ("19:00", "20:30", "Brick by Brick + Heat")]
    assert rows[0].director == "Yace Sula, Tchaiko Omawale, Joie Lee"
    assert rows[0].note.endswith("; Conversation with Joie Lee, Tchaiko Omawale & Yace Sula at 12:45pm")
    assert rows[1].director == "Akosua Adoma Owusu"
    assert rows[1].note.startswith("The Works of Akosua Adoma Owusu: Ajube Kete (2005); Boyant (2008)")
    assert rows[2].director == "Johanné Gómez Terrero"
    assert rows[2].note == "Conversation with Johanné Gómez Terrero & Loira Limbal (pre-recorded) at 6pm"
    assert {r.series for r in rows} == {parent.title} and {r.detail_url for r in rows} == {parent.detail_url}
    assert len({r.id for r in rows}) == 4


def test_bam_schedule_that_does_not_fit_is_ignored():
    from scraper.models import Screening
    from scraper.sources.bam import block_films, parse_schedule, split_programme
    schedule = parse_schedule("Intro\nSchedule:\n7pm\nHeat dir. Aicha Cherif\n8pm\nConversation with the director")
    assert block_films(schedule[1]["lines"]) is None
    noon = Screening(id="x", venue_id="bam", title="T", start="2026-10-10T12:00:00-04:00", day="2026-10-10")
    assert split_programme(noon, schedule, "America/New_York") is None      # listed at noon, schedule at 7pm
    assert parse_schedule("No running order here") is None
    other = parse_schedule("Schedule:\n12pm\nHeat dir. Aicha Cherif\n1pm\nConversation with a critic\n2pm\nBreak")
    assert split_programme(noon, other, "America/New_York")[0].end[11:16] == "13:00"   # not her talk: not joined
