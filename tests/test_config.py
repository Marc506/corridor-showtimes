"""venues.yaml loading: v2, v1 compatibility, plain-language errors; per-venue time zones."""
from datetime import date, datetime
from pathlib import Path

import pytest

from scraper.config import ConfigError, load_venues
from scraper.contract import check
from scraper.models import Screening, VenueConfig
from scraper.normalize import end_from_runtime, iso, make_id, to_local, today_local
from scraper.registry import VENUES_FILE, build_fallback, build_scraper

V1 = Path(__file__).parent / "fixtures" / "config" / "venues_v1.yaml"


def _write(tmp_path, text):
    p = tmp_path / "venues.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_v1_file_still_loads_and_matches_v2():
    old = {v.id: v for v in load_venues(V1)}
    new = {v.id: v for v in load_venues(VENUES_FILE)}
    assert old.keys() <= new.keys()                 # cinemas added since then are v2-only
    for vid, v in old.items():
        n = new[vid]
        assert (v.source, v.fallback, v.region, v.timezone, v.scraper) == \
               (n.source, n.fallback, n.region, n.timezone, n.scraper), vid
    assert old["moma"].fallback == {"adapter": "screenslate", "nid": 81}
    assert old["filmadelphia"].fallback is None and old["filmadelphia"].region == "PHL"
    assert old["metrograph"].extra["primary_cooldown_h"] == 2


def test_v2_builds_adapter_and_fallback():
    v = VenueConfig.from_dict({"id": "x", "name": "X", "timezone": "America/Los_Angeles",
                               "source": {"adapter": "custom", "module": "metrograph"},
                               "fallback": {"adapter": "screenslate", "nid": 6}})
    s = build_scraper(v, client=object())
    assert type(s).__name__ == "MetrographScraper" and str(s.tz) == "America/Los_Angeles"
    fb = build_fallback(v, client=object())
    assert fb.params == {"nid": 6} and fb.source == "screenslate"


def test_friendly_errors_zh(tmp_path):
    p = _write(tmp_path, """version: 2
venues:
  - id: a
    name: A
    source: {adapter: custom, module: bam}
  - id: b
    name: B
    source: {adapter: custom, module: bam}
  - id: c
    source: {adapter: custom, module: bam}
""")
    with pytest.raises(ConfigError) as e:
        load_venues(p, lang="zh")
    assert str(e.value) == "第 3 家影院（c）缺少 name"


def test_friendly_errors_en_several(tmp_path):
    p = _write(tmp_path, """version: 2
venues:
  - id: a
    name: A
    timezone: Mars/Olympus
    source: {adapter: custom, module: bam}
    fallback: {adapter: screenslate}
  - id: a
    name: B
    horizon_days: many
    source: {adapter: nosuch}
""")
    with pytest.raises(ConfigError) as e:
        load_venues(p, lang="en")
    assert e.value.problems == ["Venue #2 (a): `horizon_days` should be a whole number"]   # schema first
    p = _write(tmp_path, p.read_text().replace("horizon_days: many", "horizon_days: 30"))
    with pytest.raises(ConfigError) as e:
        load_venues(p, lang="en")
    msgs = e.value.problems
    assert any("timezone 'Mars/Olympus' is not a valid zone name" in m for m in msgs)
    assert any("fallback is missing parameter(s) nid" in m for m in msgs)
    assert any("Venue #2 (a): id 'a' is used twice" == m for m in msgs)
    assert any("source.adapter 'nosuch' does not exist" in m for m in msgs)


def test_yaml_syntax_error_is_one_line(tmp_path):
    p = _write(tmp_path, "version: 2\nvenues:\n  - id: [\n")
    with pytest.raises(ConfigError) as e:
        load_venues(p, lang="en")
    assert "\n" not in str(e.value) and "not valid YAML" in str(e.value)


def test_timezone_helpers():
    la = "America/Los_Angeles"
    start = to_local(datetime(2026, 11, 1, 19, 30), la)
    assert iso(start, la) == "2026-11-01T19:30:00-08:00"
    assert end_from_runtime(start, 90) == "2026-11-01T21:00:00-08:00"     # stays in the venue's zone
    assert iso(to_local(datetime(2026, 7, 1, 12), "America/Chicago")) == "2026-07-01T13:00:00-04:00"
    assert isinstance(today_local(la), date)


def test_contract_catches_offset_and_relative_urls():
    v = VenueConfig(id="x", name="X", timezone="America/Los_Angeles", source={"adapter": "custom", "module": "x"})
    start = "2026-10-01T19:00:00-04:00"                   # New York offset for an LA venue
    r = Screening(id=make_id("x", start, "F"), venue_id="x", title="F", start=start, day="2026-10-01",
                  ticket_url="/buy/1")
    problems = check(v, [r], date(2026, 9, 28))
    assert any("does not match America/Los_Angeles" in p for p in problems)
    assert any("ticket_url is not an absolute URL" in p for p in problems)
    assert check(v, [], date(2026, 9, 28)) == ["parsed 0 screenings"]
