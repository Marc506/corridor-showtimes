from datetime import date, time

import pytest

from scraper.sources.filmforum import infer_date, infer_time, parse_detail
from tests.conftest import FIXTURES


def test_infer_time_rules():
    assert infer_time("11:00") == time(11, 0)      # 11 -> am
    assert infer_time("12:50") == time(12, 50)     # 12 -> noon
    assert infer_time("1:15") == time(13, 15)      # 1-10 -> pm
    assert infer_time("10:30") == time(22, 30)
    with pytest.raises(ValueError):
        infer_time("0:30")


def test_infer_date_month_rollover():
    assert infer_date(30, date(2026, 9, 24)) == date(2026, 9, 30)
    assert infer_date(1, date(2026, 9, 28)) == date(2026, 10, 1)
    assert infer_date(29, date(2026, 10, 2)) == date(2026, 9, 29)     # run late in the week
    assert infer_date(2, date(2026, 12, 30)) == date(2027, 1, 2)


def test_filmforum_week(parse_fixture):
    rows = parse_fixture("filmforum", "now_playing.html")
    assert sorted({r.day for r in rows}) == [f"2026-09-{d}" for d in range(24, 31)]
    kw = [r for r in rows if r.title == "Kwaidan"]
    assert [r.start for r in kw] == ["2026-09-24T12:50:00-04:00"]
    assert kw[0].note == "Ends Today!"
    assert kw[0].detail_url == "https://filmforum.org/film/kwaidan-2026"
    assert all(11 <= int(r.start[11:13]) <= 23 for r in rows)


def test_filmforum_titles_unified_per_film(parse_fixture):
    rows = parse_fixture("filmforum", "now_playing.html")
    titles = {r.title for r in rows if r.detail_url.endswith("/you-had-to-be-there")}
    assert titles == {"You Had to Be There"}                # the '…' truncated variant is replaced
    assert "My Brother's Wedding" in {r.title for r in rows}


def test_filmforum_detail_pages():
    rep = parse_detail((FIXTURES / "filmforum" / "detail_kwaidan.html").read_text())
    assert rep == {"director": "Masaki Kobayashi", "year": 1964, "runtime_min": 183}
    first_run = parse_detail((FIXTURES / "filmforum" / "detail_first_run.html").read_text())
    assert first_run["director"] == "Nick Davis"            # "DIRECTED BY NICK DAVIS"
    assert (first_run["year"], first_run["runtime_min"]) == (2025, 98)     # "2025     98 MIN.     USA …"


def test_filmforum_detail_language_from_the_credit_line():
    d = parse_detail((FIXTURES / "filmforum" / "detail_my_undesirable_friends.html").read_text())
    # "2026     355 MIN.     USA     IN RUSSIAN WITH ENGLISH SUBTITLES"; the first runtime is the section's
    assert d == {"director": "Julia Loktev", "year": 2026, "runtime_min": 192, "language": "Russian"}


def test_partly_capitalised_titles():
    from scraper.normalize import language_from_text, title_case_runs
    assert title_case_runs("MY UNDESIRABLE FRIENDS: PART II – EXILE: Chapters 1-3") == \
        "My Undesirable Friends: Part II – Exile: Chapters 1-3"
    assert title_case_runs("UNZIPPED") == "Unzipped" and title_case_runs("NYFF Trivia Night") == "NYFF Trivia Night"
    assert language_from_text("IN FILIPINO, ENGLISH, AND ILOKANO WITH ENGLISH SUBTITLES") == "Filipino, English, Ilokano"

