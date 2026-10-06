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
