from scraper.sources.anthology import parse_meta

URL = "https://www.anthologyfilmarchives.org/film_screenings/calendar?view=list&month={m}&year=2026"


def rows(parse_fixture):
    return parse_fixture("anthology", ("2026-09.html", URL.format(m=9)), ("2026-10.html", URL.format(m=10)))


def test_anthology_counts_and_dates(parse_fixture):
    rs = rows(parse_fixture)
    oct_rows = [r for r in rs if r.day.startswith("2026-10")]
    assert len(oct_rows) == 90                   # 86 film-showing blocks, some with 2 times
    assert all(r.start[:10] == r.day for r in rs)


def test_anthology_multiple_times_in_one_block(parse_fixture):
    scream = [r for r in rows(parse_fixture) if r.title == "Screamplay" and r.day == "2026-10-01"]
    assert [r.start[11:16] for r in scream] == ["18:45", "21:00"]
    r = scream[0]
    assert (r.director, r.year, r.runtime_min, r.format) == ("Rufus Butler Seder", 1984, 91, "16mm-to-DCP")
    assert r.end == "2026-10-01T20:16:00-04:00"
    assert r.detail_url.endswith("#showing-61892")
    assert "veezi" in r.ticket_url


def test_anthology_series_and_title_case(parse_fixture):
    rs = rows(parse_fixture)
    alanis = next(r for r in rs if r.title == "Alanis")
    assert alanis.series == "Avatars of the Whore"
    assert alanis.year == 2017                  # language prefix before the year
    assert any(r.title == "Citizen Toxie: The Toxic Avenger IV" for r in rs)


def test_parse_meta_variants():
    assert parse_meta("1984, 91 min, 16mm-to-DCP") == (1984, 91, "16mm-to-DCP")
    assert parse_meta("Mexico/Spain, In Spanish with English subtitles, 2025, 102 min, DCP") == (2025, 102, "DCP")
    assert parse_meta("1925, 106 min, 35mm, silent") == (1925, 106, "35mm")
    assert parse_meta("1928, 62 min, 35mm. French intertitles with English voiceover.") == (1928, 62, "35mm")
    assert parse_meta("no metadata here") == (None, None, None)
