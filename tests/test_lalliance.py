import json

from scraper.sources.lalliance import parse_dir_line, parse_list
from tests.conftest import FIXTURES

LIST_URL = "https://lallianceny.org/events/?_event_categories=film"


def rows(parse_fixture):
    urls = json.loads((FIXTURES / "lalliance" / "urls.json").read_text())
    return parse_fixture("lalliance", ("events.html", LIST_URL), *urls.items())


def test_lalliance_cards():
    cards = parse_list((FIXTURES / "lalliance" / "events.html").read_text())
    assert len(cards) == 8
    assert cards[2]["title"] == "La Chienne" and cards[2]["url"].endswith("/the-remake/")


def test_lalliance_expands_schedule_and_skips_containers(parse_fixture):
    rs = rows(parse_fixture)
    titles = {r.title for r in rs}
    assert "Jean-Luc Godard: Unmade and Abandoned" not in titles      # range-only container
    assert not any(t.startswith("Family Saturdays") for t in titles)
    chienne = [r for r in rs if r.title == "La Chienne"]
    assert [r.start for r in chienne] == ["2026-09-29T16:00:00-04:00", "2026-09-29T19:00:00-04:00"]
    c = chienne[0]
    assert (c.director, c.year, c.runtime_min, c.format) == ("Jean Renoir", 1931, 93, "DCP")
    # the series comes from the container page's "Events In This Series"; the programme subtitle is a note
    assert (c.series, c.note) == ("Jean-Luc Godard: Unmade and Abandoned", "The Remake")
    assert c.screen == "Florence Gould Theater"
    assert c.ticket_url.startswith("https://buytickets.at/lalliancenewyork/")


def test_lalliance_double_bill(parse_fixture):
    r = next(r for r in rows(parse_fixture) if r.title.startswith("The Silence of the Sea"))
    assert r.director == "Jean-Luc Godard, Jean-Pierre Melville"
    assert r.year is None and r.runtime_min == 90


def test_parse_dir_line():
    assert parse_dir_line("Dir. Jean Renoir, 1931, 93 min, DCP.") == ("Jean Renoir", 1931, 93, "DCP")
    assert parse_dir_line("dirs. A and B, France, 2015, DCP") == ("A and B", 2015, None, "DCP")
    assert parse_dir_line("Directed by someone") is None


def test_lalliance_programme_without_director_lines(parse_fixture):
    """'The Audiovisual Script' lists its films as '(1981, 39 min, DCP)' with no 'Dir.' line."""
    r = next(r for r in rows(parse_fixture) if r.title == "The Audiovisual Script: Passion and Zoetrope")
    assert r.start == "2026-10-09T18:30:00-04:00"
    assert r.series == "Jean-Luc Godard: Unmade and Abandoned"      # searchable as "Godard"
    assert (r.format, r.runtime_min, r.director) == ("DCP", 118, None)


def test_series_members_ignores_site_menus():
    from scraper.sources.lalliance import series_members
    html = (FIXTURES / "lalliance" / "jean-luc-godard-unmade-and-abandoned.html").read_text()
    members = series_members(html)
    assert "the-audiovisual-script" in members and "the-remake" in members
    assert "family-saturdays-fall-26" not in members and "le-gala-de-lalliance-2026" not in members
    assert series_members("<html><a href='/event/x/'>menu</a></html>") == []


def test_credit_line_parsing():
    from scraper.sources.lalliance import CREDIT
    for line, want in [("(1981, 7 min, DCP)", ("1981", "7", "DCP")),
                       ("), (1982, 53 min, DCP)", ("1982", "53", "DCP")),
                       (", 1982, 11 min, DCP)", ("1982", "11", "DCP")),
                       ("(2006, 8 min)", ("2006", "8", None))]:
        assert CREDIT.search(line).groups() == want, line
    assert CREDIT.search("Run Time: 118 min") is None
    assert CREDIT.search("released in 1981, it ran for years") is None
