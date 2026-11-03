"""MoMA: the JSON file dropped into inbox/moma/ (scraper/sources/moma.py)."""
import os
import time

import pytest

from scraper.base import ScrapeError
from scraper.contract import check_venue
from scraper.sources import moma as M
from tests.conftest import scraper_for


def test_moma_contract():
    problems = check_venue("moma")
    assert not problems, "\n".join(problems)


def test_moma_records(parse_fixture):
    rows = parse_fixture("moma", ("moma_films.json", "file://inbox/moma/moma_films_2026-11-03.json"))
    trial = next(r for r in rows if r.title.startswith("The Trial"))
    assert (trial.director, trial.year, trial.runtime_min, trial.series, trial.screen) == \
        ("Sergei Loznitsa", 2018, 129, "Sergei Loznitsa", "Theater 2")
    assert trial.end == "2026-11-03T21:39:00-05:00" and trial.ticket_url.startswith("https://membership.moma.org/")
    pair = next(r for r in rows if " + " in r.title)                            # two films: "A + B", no single year
    assert pair.title == "Factory (ФАБРИКА) + Landscape (ЛАНДШАФТ)" and pair.year is None
    programme = next(r for r in rows if r.title == "Sergei Loznitsa’s Short Films: Program 1")   # no films listed
    assert programme.director is None and programme.runtime_min == 103
    assert any(r.note == "For kids" for r in rows)


def test_inbox_keeps_only_the_newest_and_flags_an_old_one(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "ROOT", tmp_path)
    s = scraper_for("moma")
    box = tmp_path / "inbox" / "moma"
    with pytest.raises(ScrapeError, match="no MoMA file"):
        s.fetch()
    for i, name in enumerate(["moma_films_2026-10-20.json", "moma_films_2026-11-03.json"]):
        (box / name).write_text("[]")
        os.utime(box / name, (time.time() - (1 - i) * 86400,) * 2)
    [page] = s.fetch()
    assert page.url.endswith("moma_films_2026-11-03.json") and [p.name for p in box.iterdir()] == ["moma_films_2026-11-03.json"]
    os.utime(box / "moma_films_2026-11-03.json", (time.time() - 12 * 86400,) * 2)
    with pytest.raises(ScrapeError, match="12 days old"):
        s.fetch()
