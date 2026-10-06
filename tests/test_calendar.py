"""Add-to-calendar: venues.yaml `location:` and the .ics the page builds (site/calendar.js, run under Node)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from scraper.config import ConfigError, load_venues
from scraper.registry import VENUES_FILE

ROOT = Path(__file__).resolve().parent.parent
CALENDAR_JS = ROOT / "site" / "calendar.js"


def _write(tmp_path, text):
    p = tmp_path / "venues.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_every_public_venue_has_an_address_and_coordinates():
    for v in load_venues(VENUES_FILE):
        loc = v.location or {}
        assert loc.get("address") and len(loc.get("geo") or []) == 2, v.id
        for place in loc.get("places", []):
            assert place.get("address") and len(place.get("geo") or []) == 2, (v.id, place)


def test_location_is_validated(tmp_path):
    base = "version: 2\nvenues:\n  - id: a\n    name: A\n    source: {adapter: custom, module: bam}\n"
    assert load_venues(_write(tmp_path, base + '    location: {address: "1 Main St, Town, NY 10001"}\n'))[0].location
    with pytest.raises(ConfigError) as e:
        load_venues(_write(tmp_path, base + "    location: {geo: [140.7, -73.9]}\n"), lang="en")
    assert "location.geo.0" in str(e.value)
    with pytest.raises(ConfigError):
        load_venues(_write(tmp_path, base + "    location: {geo: [40.7]}\n"), lang="en")
    with pytest.raises(ConfigError):
        load_venues(_write(tmp_path, base + "    location: {places: [{name: X}]}\n"), lang="en")   # match is required


VENUE = {
    "id": "flc", "name": "Film at Lincoln Center", "website": "https://www.filmlinc.org/",
    "location": {
        "address": "144 W 65th St, New York, NY 10023", "geo": [40.77345, -73.98357],
        "places": [{"match": "Walter Reade", "name": "Walter Reade Theater",
                    "address": "165 W 65th St, New York, NY 10023", "geo": [40.77409, -73.98431]}],
    },
}
SHOW = {
    "id": "abc123", "venue_id": "flc", "title": "Happy Together; Days of Being Wild, 35mm",
    "start": "2026-10-06T19:00:00-04:00", "end": "2026-10-06T20:36:00-04:00", "day": "2026-10-06",
    "director": "Wong Kar-wai", "year": 1997, "runtime_min": 96, "format": "35mm", "language": "Cantonese",
    "series": "Wong Kar-wai: World of Wong", "screen": "Walter Reade Theater", "note": None,
    "ticket_url": "https://tickets.example.org/1", "detail_url": "https://www.filmlinc.org/films/happy-together/",
}


def _node(script: str):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    out = subprocess.run(["node", "-e", f"const C = require({json.dumps(str(CALENDAR_JS))});\n{script}"],
                         capture_output=True, text=True, timeout=30, check=True)
    return json.loads(out.stdout)


def _unfold(ics: str) -> list[str]:
    return ics.replace("\r\n ", "").split("\r\n")


def test_ics_has_time_title_and_a_map_location():
    r = _node(f"""
      const s = {json.dumps(SHOW)}, v = {json.dumps(VENUE)};
      const ics = C.toICS(C.eventFor(s, v, "en"), new Date("2026-10-01T00:00:00Z"));
      console.log(JSON.stringify({{ics, name: C.fileName(s)}}));""")
    ics = r["ics"]
    assert ics.endswith("\r\n") and "\n" not in ics.replace("\r\n", "")
    assert all(len(line.encode()) <= 75 for line in ics.split("\r\n"))
    lines = _unfold(ics)
    assert lines[0] == "BEGIN:VCALENDAR" and lines[-2] == "END:VCALENDAR"
    assert "UID:abc123@corridor-showtimes" in lines
    assert "DTSTART:20261006T230000Z" in lines and "DTEND:20261007T003600Z" in lines   # 7pm–8:36pm New York
    assert r"SUMMARY:Happy Together\; Days of Being Wild\, 35mm" in lines
    loc = r"Walter Reade Theater\, 165 W 65th St\, New York\, NY 10023"
    assert f"LOCATION:{loc}" in lines                                             # the screen's building
    assert "GEO:40.77409;-73.98431" in lines
    apple = next(x for x in lines if x.startswith("X-APPLE-STRUCTURED-LOCATION"))
    assert apple == ('X-APPLE-STRUCTURED-LOCATION;VALUE=URI;X-ADDRESS="165 W 65th St, New York, NY 10023";'
                     'X-APPLE-RADIUS=70;X-TITLE="Walter Reade Theater, 165 W 65th St, New York, NY 10023"'
                     ':geo:40.77409,-73.98431')                                    # title == LOCATION text
    desc = next(x for x in lines if x.startswith("DESCRIPTION:"))
    assert "Wong Kar-wai · 1997 · 96 min · 35mm · Cantonese" in desc and r"Tickets: https://tickets.example.org/1" in desc
    assert "URL:https://tickets.example.org/1" in lines
    assert r["name"] == "Happy Together; Days of Being Wild, 35mm 2026-10-06.ics"


def test_unknown_runtime_other_screen_and_no_location():
    s = dict(SHOW, end=None, runtime_min=None, screen="Francesca Beale Theater", title="無間道")
    r = _node(f"""
      const s = {json.dumps(s)}, v = {json.dumps(VENUE)};
      const a = C.toICS(C.eventFor(s, v, "zh"), new Date("2026-10-01T00:00:00Z"));
      const b = C.toICS(C.eventFor(s, {{id: "x", name: "Nitehawk Williamsburg"}}, "zh"));
      console.log(JSON.stringify({{a, b}}));""")
    a, b = _unfold(r["a"]), _unfold(r["b"])
    assert "DTEND:20261007T010000Z" in a                                      # 2 hours when the runtime is unknown
    assert r"LOCATION:Film at Lincoln Center\, 144 W 65th St\, New York\, NY 10023" in a   # the venue's own building
    assert "SUMMARY:無間道" in a and any("片长未知" in x for x in a)
    assert all(len(line.encode()) <= 75 for line in r["a"].split("\r\n"))     # folding never splits a character
    assert "LOCATION:Nitehawk Williamsburg" in b                              # no address yet: just the name
    assert not any(x.startswith(("GEO", "X-APPLE")) for x in b)


def test_page_loads_calendar_script_and_publish_copies_it():
    assert '<script src="calendar.js"></script>' in (ROOT / "site" / "index.html").read_text()
    assert "site/calendar.js" in (ROOT / "scripts" / "publish.sh").read_text()
    assert "site/calendar.js" in (ROOT / ".github" / "workflows" / "refresh.yml").read_text()
