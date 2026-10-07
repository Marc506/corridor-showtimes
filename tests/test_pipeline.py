"""Store + validation behaviour that every venue relies on."""
from datetime import date

from scraper.models import Screening, VenueConfig, VenueStatus
from scraper.normalize import make_id
from scraper.run import validate
from scraper.store import Store


def _s(venue, start, title="Film"):
    return Screening(id=make_id(venue, start, title), venue_id=venue, title=title, start=start,
                     day=start[:10], scraped_at="now")


def test_validate_zero_rows_fails_unless_allowed():
    v = VenueConfig(id="x", name="X", scraper="x")
    _, st = validate(v, [], VenueStatus("x", "ok"), None, today=date(2026, 9, 24))
    assert st.status == "failed"
    v.allow_empty = True
    _, st = validate(v, [], VenueStatus("x", "ok"), None, today=date(2026, 9, 24))
    assert st.status == "ok"


def test_validate_window_and_horizon():
    v = VenueConfig(id="x", name="X", scraper="x", horizon_days=30)
    rows = [_s("x", "2026-09-20T19:00:00-04:00"),   # past: dropped silently
            _s("x", "2026-09-24T19:00:00-04:00"),
            _s("x", "2026-11-10T19:00:00-05:00"),   # beyond horizon but valid: silently cut
            _s("x", "2027-06-01T19:00:00-04:00")]   # beyond horizon+60: dropped with WARN
    kept, st = validate(v, rows, VenueStatus("x", "ok"), None, today=date(2026, 9, 24))
    assert [r.day for r in kept] == ["2026-09-24"] and st.count == 1


def test_store_success_then_failure_keeps_data(tmp_path, monkeypatch):
    monkeypatch.setattr("scraper.store.today_local", lambda tz=None: date(2026, 9, 24))
    store = Store(tmp_path / "t.sqlite")
    rows = [_s("x", "2026-09-25T19:00:00-04:00"), _s("x", "2026-09-26T19:00:00-04:00")]
    st = store.apply_success("x", rows, VenueStatus("x", "ok", fetched_at="T1"))
    assert (st.count, st.horizon_end) == (2, "2026-09-26")

    # a later success replaces future rows (the 26th disappeared)
    store.apply_success("x", rows[:1], VenueStatus("x", "ok", fetched_at="T2"))
    assert len(store.screenings_since("2026-09-24")) == 1

    # failure: rows kept, status stale, fetched_at from last success
    st = store.apply_failure("x", VenueStatus("x", "failed", error="boom"))
    assert (st.status, st.fetched_at, st.count, st.error) == ("stale", "T2", 1, "boom")
    assert len(store.screenings_since("2026-09-24")) == 1

    # a venue that never succeeded is "failed", not "stale"
    assert store.apply_failure("y", VenueStatus("y", "failed", error="x")).status == "failed"


def test_run_lock_is_exclusive(tmp_path, monkeypatch):
    from scraper import run
    monkeypatch.setattr(run, "LOCK_PATH", tmp_path / ".run.lock")
    first = run.acquire_run_lock()
    assert first and run.acquire_run_lock() is False
    first.close()                                  # released -> next run can go
    again = run.acquire_run_lock()
    assert again
    again.close()


def test_seed_from_export_keeps_data_through_a_failed_ci_run(tmp_path, monkeypatch):
    """CI starts with an empty database: seeding from the last export makes a failure 'stale', not 'failed'."""
    monkeypatch.setattr("scraper.store.today_local", lambda tz=None: date(2026, 9, 24))
    old = Store(tmp_path / "old.sqlite")
    old.apply_success("x", [_s("x", "2026-09-25T19:00:00-04:00")], VenueStatus("x", "ok", fetched_at="T1"))
    from scraper.export import build_payload
    monkeypatch.setattr("scraper.export.today_local", lambda tz=None: date(2026, 9, 24))
    monkeypatch.setattr("scraper.export.load_venues",
                        lambda: [VenueConfig(id="x", name="X", source={"adapter": "custom", "module": "x"})])
    payload = build_payload(old)

    fresh = Store(tmp_path / "ci.sqlite")
    assert fresh.seed_from_export(payload) == 1
    assert fresh.seed_from_export(payload) == 1 and len(fresh.screenings_since("2026-09-24")) == 1   # idempotent
    st = fresh.apply_failure("x", VenueStatus("x", "failed", error="HTTP 403"))
    assert (st.status, st.fetched_at, st.count) == ("stale", "T1", 1)


def test_dedupe_keeps_one_film_starting_on_two_screens():
    from scraper.base import dedupe
    from scraper.models import Screening
    from scraper.normalize import make_id
    start = "2026-10-10T16:00:00-04:00"

    def show(screen, url=None):
        return Screening(id=make_id("ritz", start, "Hamnet"), venue_id="ritz", title="Hamnet", start=start,
                         day=start[:10], screen=screen, ticket_url=url)
    rows = dedupe([show("Screen 4", "t/4"), show("Screen 1", "t/1"), show("Screen 4", "dup")])
    assert [(r.screen, r.ticket_url) for r in rows] == [("Screen 1", "t/1"), ("Screen 4", "t/4")]
    assert rows[0].id == make_id("ritz", start, "Hamnet") and rows[1].id != rows[0].id     # stable, unique
    again = dedupe([show("Screen 1", "t/1"), show("Screen 4", "t/4")])
    assert [r.id for r in again] == [r.id for r in rows]                                    # order-independent
    assert len(dedupe([show(None), show("Screen 2")])) == 1         # no screen named twice: the same screening


def test_regular_runs_hide_new_films_in_their_run_only():
    from scraper.export import regular_runs

    def show(i, venue, title, day, year, series=None, note=None):
        return {"id": f"{venue}-{title}-{i}", "venue_id": venue, "title": title, "day": day, "year": year,
                "series": series, "note": note}
    rows = (
        [show(i, "ff", "Primetime", f"2026-10-{6 + i // 3:02d}", 2026) for i in range(9)]          # first run, no series
        + [show(i, "county", "Bad Apples", f"2026-10-{6 + i:02d}", 2026) for i in range(3)]       # small house, 1 a day
        + [show(i, "flc", "Behemoth!", f"2026-10-{2 + i:02d}", 2026, "NYFF") for i in range(8)]   # festival: 1 a day
        + [show(i, "flc", "Fatherland", f"2026-10-{6 + i // 4:02d}", 2026, "NYFF") for i in range(12)]   # run under a festival label
        + [show(i, "ff", "Kwaidan", f"2026-10-{6 + i // 4:02d}", 1964) for i in range(12)]          # repertory: never
        + [show(0, "bam", "Possible Love", "2026-10-07", 2026), show(1, "bam", "Possible Love", "2026-10-08", 2026)]
        + [show(i, "ff", "Mystery", f"2026-10-{6 + i:02d}", None) for i in range(5)]               # no year: kept
        + [show(99, "ff", "Primetime", "2026-10-09", 2026, note="Q&A with Lance Oppenheim")]      # special event: kept
        + [show(i, "ritz", "Primetime", f"2026-10-{6 + i:02d}", 2026) for i in range(4)]          # ... opened widely
        + [show(i, "ambler", "Bad Apples", f"2026-10-{6 + i:02d}", 2026) for i in range(3)]
        + [show(i, "bam", "Fatherland", f"2026-10-{6 + i:02d}", 2026) for i in range(3)]          # a second run
        + [show(i, "coolidge", "Tony (2026)", f"2026-10-{6 + i:02d}", 2026) for i in range(3)]    # same film, other spelling
        + [show(i, "bam", "Tony", f"2026-10-{6 + i:02d}", 2026) for i in range(3)]
        + [show(i, "ff", "My Undesirable Friends", f"2026-10-{6 + i // 3:02d}", 2026) for i in range(9)]   # one cinema only
    )
    hidden = regular_runs(rows, rows, 2026)
    by = lambda t: {r["id"] in hidden for r in rows if r["title"] == t and not r.get("note")}  # noqa: E731
    assert by("Primetime") == {True} and by("Bad Apples") == {True} and by("Fatherland") == {True}
    assert by("Behemoth!") == {False} and by("Kwaidan") == {False} and by("Possible Love") == {False}
    assert by("Mystery") == {False}
    assert by("Tony (2026)") == {True} and by("Tony") == {True}
    assert by("My Undesirable Friends") == {False}             # a run at a single cinema: an exclusive, kept
    assert "ff-Primetime-99" not in hidden


def test_regular_runs_reference_chain_and_streaming():
    from scraper.export import regular_runs

    def show(i, venue, title, day, year=2026, **kw):
        return {"id": f"{venue}-{title}-{i}", "venue_id": venue, "title": title, "day": day, "year": year, **kw}
    days = [f"2026-10-{d:02d}" for d in range(6, 13)]
    rows = (
        [show(i, "bam", "Naza", days[i % 7]) for i in range(10)]                    # one cinema here...
        + [show(i, "bam", "Cameron Winter at Carnegie Hall", days[i % 7]) for i in range(10)]
        + [show(i, "kendall", "Animals", days[i % 7], streaming=True) for i in range(10)]   # Netflix, same day
        + [show(i, "ff", "My Undesirable Friends", days[i % 7]) for i in range(10)]
    )
    chain = ([show(i, "ref-alamo", "Naza", days[i % 7], None) for i in range(12)]          # ...but a run at the chain
             + [show(i, "ref-alamo", "Cameron Winter at Carnegie Hall", days[0], None) for i in range(2)])  # a special
    hidden = regular_runs(rows, rows + chain, 2026, {"ref-alamo"})
    by = lambda t: {r["id"] in hidden for r in rows if r["title"] == t}  # noqa: E731
    assert by("Naza") == {True} and by("Animals") == {True}
    assert by("Cameron Winter at Carnegie Hall") == {False} and by("My Undesirable Friends") == {False}


def test_reference_venues_are_never_exported(tmp_path, monkeypatch):
    from scraper import export as E
    from scraper.models import VenueConfig
    monkeypatch.setattr(E, "load_venues", lambda: [
        VenueConfig(id="ff", name="Film Forum", source={"adapter": "custom", "module": "filmforum"}),
        VenueConfig(id="ref", name="Chain", reference=True, source={"adapter": "alamo", "market": "nyc"})])
    store = Store(tmp_path / "db.sqlite")
    payload = E.build_payload(store)
    assert [v["id"] for v in payload["venues"]] == ["ff"]



def test_exported_venues_are_grouped_by_city(tmp_path, monkeypatch):
    """A cinema appended at the end of venues.yaml still sits with the rest of its city on the page."""
    from scraper import export as E
    from scraper.models import VenueConfig
    src = {"adapter": "custom", "module": "x"}
    monkeypatch.setattr(E, "load_venues", lambda: [
        VenueConfig(id="ff", name="Film Forum", region="NYC", source=src),
        VenueConfig(id="pfs", name="PFS", region="PHL", source=src),
        VenueConfig(id="brattle", name="Brattle", region="BOS", source=src),
        VenueConfig(id="paris", name="Paris", region="NYC", source=src)])
    payload = E.build_payload(Store(tmp_path / "db.sqlite"))
    assert [v["id"] for v in payload["venues"]] == ["ff", "paris", "pfs", "brattle"]
