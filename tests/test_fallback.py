"""run.py degradation: primary fails -> the venue's fallback; cooldown skips the primary next time."""
from datetime import date

from scraper import run
from scraper.models import Screening, VenueConfig, VenueStatus
from scraper.normalize import make_id
from scraper.store import Store


def _row(src="primary"):
    start = "2026-09-25T19:00:00-04:00"
    return Screening(id=make_id("v", start, "F"), venue_id="v", title="F", start=start, day="2026-09-25",
                     source=src, scraped_at="now")


class FailingPrimary:
    calls = 0

    def __init__(self, venue, client=None):
        self.venue = venue

    def run(self, save_raw=True):
        FailingPrimary.calls += 1
        return [], VenueStatus(self.venue.id, "failed", error="ScrapeError: Cloudflare")


class FakeScreenslate(FailingPrimary):
    def run(self, save_raw=True):
        return [_row("screenslate")], VenueStatus(self.venue.id, "ok", fetched_at="T", source="screenslate")


def _setup(monkeypatch, tmp_path, cooldown=20):
    monkeypatch.setattr(run, "build_scraper", lambda v, client=None: FailingPrimary(v))
    monkeypatch.setattr(run, "build_fallback", lambda v, client=None: FakeScreenslate(v) if v.fallback else None)
    monkeypatch.setattr(run, "today_local", lambda tz=None: date(2026, 9, 24))
    monkeypatch.setattr("scraper.store.today_local", lambda tz=None: date(2026, 9, 24))
    FailingPrimary.calls = 0
    venue = VenueConfig(id="v", name="V", scraper="x", screenslate_nid=81,
                        extra={"primary_cooldown_h": cooldown})
    return venue, Store(tmp_path / "t.sqlite")


def test_fallback_then_cooldown(monkeypatch, tmp_path):
    venue, store = _setup(monkeypatch, tmp_path)
    st = run.run_venue(venue, store, client=None, dry_run=False)
    assert (st.status, st.source, st.count) == ("ok", "screenslate", 1)
    assert st.error == "primary failed: ScrapeError: Cloudflare"
    assert store.primary_failed_at("v") and FailingPrimary.calls == 1

    st = run.run_venue(venue, store, client=None, dry_run=False)     # within cooldown
    assert FailingPrimary.calls == 1                                  # primary not tried again
    assert st.source == "screenslate"
    assert st.error.startswith("primary in cooldown") and st.error.endswith("last failure: ScrapeError: Cloudflare")


def test_no_cooldown_retries_primary(monkeypatch, tmp_path):
    venue, store = _setup(monkeypatch, tmp_path, cooldown=0)
    run.run_venue(venue, store, client=None, dry_run=False)
    run.run_venue(venue, store, client=None, dry_run=False)
    assert FailingPrimary.calls == 2


def test_force_primary_disables_fallback(monkeypatch, tmp_path):
    venue, store = _setup(monkeypatch, tmp_path)
    st = run.run_venue(venue, store, client=None, dry_run=False, force_source="primary")
    assert st.status == "failed" and st.source == "primary"


def test_fallback_can_be_any_adapter(monkeypatch, tmp_path):
    venue, store = _setup(monkeypatch, tmp_path, cooldown=0)
    venue.fallback = {"adapter": "veezi", "site_token": "x" * 26}
    st = run.run_venue(venue, store, client=None, dry_run=False)
    assert (st.status, st.source) == ("ok", "veezi")
    assert store.screenings_since("2026-09-24")[0]["source"] == "screenslate"   # rows keep their own label


def test_no_fallback_configured(monkeypatch, tmp_path):
    venue, store = _setup(monkeypatch, tmp_path, cooldown=0)
    venue.fallback = None
    st = run.run_venue(venue, store, client=None, dry_run=False)
    assert st.status == "failed" and st.error == "ScrapeError: Cloudflare"
