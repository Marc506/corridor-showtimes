"""Directors from screenslate for screenings the cinema and TMDB left without one (offline)."""
import json

import pytest

from scraper import crossref as X
from scraper.models import RawPage, Screening
from scraper.normalize import make_id
from tests.conftest import FIXTURES, scraper_for

SS = FIXTURES / "screenslate"


def _row(title, start, director=None, source="primary"):
    return Screening(id=make_id("moma", start, title), venue_id="moma", title=title, start=start,
                     day=start[:10], director=director, source=source, scraped_at="now")


def test_title_similarity():
    assert X.title_similarity("The Audiovisual Script: Passion and Zoetrope",
                              "Audiovisual Script – Passion & Zoetrope") == 1.0
    assert X.title_similarity("Ip Man 4", "Ip Man 4: The Finale") == 1.0
    assert X.title_similarity("Artificial", "Behemoth!") == 0.0


def test_best_match_rules():
    a = _row("Artificial", "2026-10-02T17:00:00-04:00", source="screenslate")
    b = _row("Behemoth!", "2026-10-02T17:05:00-04:00", source="screenslate")
    far = _row("Artificial", "2026-10-02T19:00:00-04:00", source="screenslate")
    target = _row("Artificial", "2026-10-02T17:00:00-04:00")
    assert X.best_match(target, [a, b, far]) is a                        # right title at the right time
    assert X.best_match(target, [far]) is None                            # right title, wrong time
    assert X.best_match(_row("Totally Different", "2026-10-02T17:00:00-04:00"), [a, b]) is None
    lone = _row("NYFF: Artificial (Guadagnino)", "2026-10-02T17:00:00-04:00", source="screenslate")
    assert X.best_match(_row("Artificial", "2026-10-02T17:00:00-04:00"), [lone]) is lone
    twin = _row("Artificial", "2026-10-02T17:02:00-04:00", source="screenslate")
    assert X.best_match(target, [a, twin]) is None                        # two equally good: don't guess


@pytest.fixture
def fake_screenslate(monkeypatch, tmp_path):
    """The real screenslate adapter, with its HTTP replaced by the saved MoMA responses."""
    monkeypatch.setattr(X, "CACHE_DIR", tmp_path / "cache")
    venue = scraper_for("moma").venue
    venue.fallback = {"adapter": "screenslate", "nid": 81}
    ss = X.build_fallback(venue, client=object())
    calls = []

    def get_page(url, ext="html", params=None):
        calls.append((url, params))
        if url.endswith("/date"):
            f = SS / f"date_{params['date']}.json"
            body = f.read_text() if f.exists() else "[]"
        else:
            wanted = set(url.rsplit("/", 1)[1].split("+"))
            body = json.dumps([r for r in json.loads((SS / "ids.json").read_text()) if str(r["nid"]) in wanted])
        return RawPage(url=url, body=body, fetched_at="2026-09-27T12:00:00Z", ext=ext)

    ss.get_page = get_page
    monkeypatch.setattr(X, "build_fallback", lambda v, client=None: ss)
    return venue, calls


def test_fills_director_runtime_and_year_from_the_same_screening(fake_screenslate):
    venue, calls = fake_screenslate
    ip = _row("Ip Man 4", "2026-09-27T13:30:00-04:00")                   # primary, no director
    kept = _row("Some Film", "2026-09-27T13:30:00-04:00", director="Listed By Cinema")
    changed = X.fill_directors_from_screenslate([ip, kept], venue, client=None)
    assert changed == [ip]
    assert (ip.director, ip.year, ip.runtime_min) == ("Wilson Yip", 2019, 107)
    assert ip.end == "2026-09-27T15:17:00-04:00"
    assert kept.director == "Listed By Cinema"
    days = [p for u, p in calls if u.endswith("/date")]
    assert [p["date"] for p in days] == ["20260927"]                      # only the day that needed it


def test_uses_the_cache_on_the_next_run(fake_screenslate):
    venue, calls = fake_screenslate
    X.fill_directors_from_screenslate([_row("Ip Man 4", "2026-09-27T13:30:00-04:00")], venue, client=None)
    n = len(calls)
    X.fill_directors_from_screenslate([_row("Ip Man 4", "2026-09-27T13:30:00-04:00")], venue, client=None)
    assert len(calls) == n                                                # nothing fetched again


def test_skips_venues_without_screenslate_and_fallback_rows(fake_screenslate):
    venue, calls = fake_screenslate
    fb_row = _row("Ip Man 4", "2026-09-27T13:30:00-04:00", source="screenslate")
    assert X.fill_directors_from_screenslate([fb_row], venue, client=None) == [] and calls == []
    venue.fallback = None
    assert X.fill_directors_from_screenslate([_row("Ip Man 4", "2026-09-27T13:30:00-04:00")], venue, None) == []


def test_director_list_dedupes_and_caps():
    assert X.director_list("Laird Sutton, Bill Chamberlain, Laird Sutton, Ann Hershey") == \
        "Laird Sutton, Bill Chamberlain, Ann Hershey"
    assert X.director_list("Lazare Lazarus, Lazare Lazarus") == "Lazare Lazarus"
    assert X.director_list("Joel & Ethan Coen") == "Joel & Ethan Coen"             # one credit, not split
    assert X.director_list("A, B, C, D, E") == "A, B, C, …"
