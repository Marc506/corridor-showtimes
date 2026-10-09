"""The Secret Cinema: its hand-written home page (SOURCES.md §18)."""
from scraper.contract import check_venue
from scraper.normalize import response_text


def test_secret_cinema_contract():
    problems = check_venue("secret-cinema")
    assert not problems, "\n".join(problems)


def test_secret_cinema_sections(parse_fixture):
    rows = parse_fixture("secret-cinema", ("page_0.html", "https://www.thesecretcinema.com/"))
    assert [(r.start, r.end, r.title, r.screen, r.format) for r in rows] == [
        ("2026-10-08T20:00:00-04:00", None,
         "Archive Discoveries 2026: Unseen Curiosities from the Secret Cinema Collection", "The Rotunda", "Film"),
        ("2026-10-16T19:30:00-04:00", "2026-10-16T23:30:00-04:00",
         "Science After Hours event “Fright Nite”", "The Franklin Institute", "16mm")]
    assert rows[0].note.startswith("Free; Invisible Walls (1968, dir. Richard A. Cowan); Geronimo Jones (1970,")
    assert "Time Out for a Hobby (1950s, dir. Neil Harvey)" in rows[0].note
    # "FUTURE SECRET CINEMA EVENTS (more info soon)" has dates but no times: not screenings yet
    assert not any(r.day == "2026-10-23" for r in rows)


def test_utf16_pages_are_decoded():
    page = "<p>Thursday, October 8, 2026</p>"
    assert response_text(page.encode("utf-16"), "garbled") == page
    assert response_text(page.encode("utf-8"), page) == page
