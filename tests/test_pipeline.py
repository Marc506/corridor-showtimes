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
    monkeypatch.setattr("scraper.store.today_local", lambda: date(2026, 9, 24))
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
