"""Platform adapters: parsing details on real pages, and detect() on saved sites (fully offline).

The contract (tests/test_contract.py) already runs every demo venue in fixtures/platforms/venues.yaml;
these tests pin the platform-specific parts.
"""
import json
from pathlib import Path

import pytest

from scraper.adapters import detectable_adapters, get_adapter_class, known_adapters
from scraper.base import dedupe
from scraper.config import load_venues
from scraper.contract import load_fixture
from scraper.models import RawPage, VenueConfig
from scraper.probe import ProbeResponse, SiteProbe
from scraper.registry import build_scraper

P = Path(__file__).parent / "fixtures" / "platforms"
DEMO = {v.id: v for v in load_venues(P / "venues.yaml")}


def rows(venue_id):
    v = DEMO[venue_id]
    return dedupe(build_scraper(v, client=object()).parse(load_fixture(P, v.extra["fixture"]).pages))


def detect(adapter, url, pages):
    spec = {u: (P / f if isinstance(f, str) else (P / f[0], *f[1:]) if isinstance(f, tuple) else f)
            for u, f in pages.items()}
    probe = SiteProbe.offline(url, spec).start()
    return get_adapter_class(adapter).detect(probe), probe


def test_registry_lists_every_platform():
    names = set(known_adapters())
    assert {"agile", "filmbot", "veezi", "jsonld", "tribe", "squarespace", "ics", "alamo",
            "wp-my-calendar", "eventive", "spektrix", "screenslate"} <= names
    order = [c.adapter_name for c in detectable_adapters()]
    assert order.index("filmbot") < order.index("veezi") < order.index("agile") < order.index("jsonld")
    assert "screenslate" not in order                   # a fallback, never detected


# ---------- filmbot ----------
def test_filmbot_listings():
    rs = rows("nitehawk")
    assert len(rs) == 106
    r = next(r for r in rs if r.title == "Resident Evil")           # "(2026)" suffix moved into year
    assert (r.year, r.runtime_min) == (2026, 94)
    assert r.start == "2026-09-28T15:45:00-04:00" and r.end == "2026-09-28T17:19:00-04:00"
    assert r.ticket_url == "https://nitehawkcinema.com/williamsburg/purchase/24327553/"


def test_filmbot_posts_shape_in_la():
    rs = rows("vidiots")
    r = next(r for r in rs if r.title == "9 to 5")
    assert r.start == "2026-10-09T16:00:00-07:00" and r.runtime_min == 117
    assert any(r.note == "Sold out" for r in rs)


def test_filmbot_detect_branch_path():
    c, _ = detect("filmbot", "https://nitehawkcinema.com/williamsburg/", {
        "https://nitehawkcinema.com/williamsburg/": "filmbot/nitehawk_home.html",
        "https://nitehawkcinema.com/williamsburg/wp-json/nj/v1/showtime/listings": "filmbot/nitehawk_listings.json"})
    assert c.source == {"adapter": "filmbot", "base_url": "https://nitehawkcinema.com/williamsburg"}


def test_filmbot_detect_negative():
    c, _ = detect("filmbot", "https://uniondocs.org/", {"https://uniondocs.org/": "tribe/uniondocs_home.html"})
    assert c is None


# ---------- veezi ----------
def test_veezi_jsonld_and_html_metadata():
    rs = rows("roxy")
    idle = next(r for r in rs if r.title == "Idlewild")               # "(35mm)" moved into format
    assert (idle.format, idle.runtime_min, idle.start) == ("35mm", 121, "2026-09-28T19:00:00-04:00")
    assert idle.ticket_url.startswith("https://ticketing.uswest.veezi.com/purchase/")
    afa = rows("anthology-veezi")
    alanis = next(r for r in afa if r.title == "Alanis")
    assert (alanis.director, alanis.year, alanis.format, alanis.language) == ("Anahí Berneri", 2017, "DCP", "Spanish")


def test_veezi_html_fallback_matches_jsonld():
    v = DEMO["roxy"]
    page = load_fixture(P, v.extra["fixture"]).pages[0]
    stripped = RawPage(page.url, page.body.replace("application/ld+json", "text/plain"), page.fetched_at)
    s = build_scraper(v, client=object())
    via_ld = {(r.start, r.title) for r in dedupe(s.parse([page]))}
    via_html = {(r.start, r.title) for r in dedupe(s.parse([stripped]))}
    assert len(via_html) >= 0.9 * len(via_ld) and len(via_html & via_ld) >= 0.9 * len(via_html)


def test_veezi_detect():
    c, _ = detect("veezi", "https://www.roxycinemanewyork.com/", {
        "https://www.roxycinemanewyork.com/": "veezi/roxy_home.html"})
    assert c.source == {"adapter": "veezi", "site_token": "tt17e5ajy3v48kh5b2kremvnz4", "region": "uswest"}


# ---------- agile ----------
def test_agile_generic_feed():
    rs = rows("gables")
    assert len(rs) == 58
    r = next(r for r in rs if r.title == "8 1/2")
    assert (r.director, r.year, r.runtime_min, r.language) == ("Federico Fellini", 1963, 138, "Italian")
    assert r.series is None                                            # "Repertory" is a generic type


def test_agile_detect_entry_point_guid():
    feed = ("https://prod3.agileticketing.net/websales/feed.ashx?guid=6ec0e98b-d23e-4240-acce-5ffa059e6887"
            "&showslist=true&withmedia=false&format=json&v=latest")
    c, probe = detect("agile", "https://gablescinema.com/", {
        "https://gablescinema.com/": "agile/gables_home.html", feed: "agile/gables_feed.json"})
    assert c.source == {"adapter": "agile", "guid": "6ec0e98b-d23e-4240-acce-5ffa059e6887",
                        "host": "prod3.agileticketing.net"}
    assert probe.requests <= 12


def test_agile_detect_without_feed_guid_hints_recipe():
    feed = ("https://store.coolidge.org/websales/feed.ashx?guid={g}&showslist=true&withmedia=false&format=json&v=latest")
    c, probe = detect("agile", "https://coolidge.org/", {
        "https://coolidge.org/": "agile/coolidge_home.html",
        feed.format(g="2227d6a5-68f5-41c2-b22e-813c872c64f4"): "agile/coolidge_feed_empty.json"})
    assert c is None and "agile_no_feed_guid" in probe.hints


# ---------- tribe / ics ----------
def test_tribe_filters_categories_and_workshops():
    rs = rows("uniondocs")
    assert [r.title for r in rs] == ["Fall of Freedom — Under Pressure: How to Document “Unprecedented Times”",
                                     "Zodiac Killer Project", "Under the Sky of Fetishes"]
    assert rs[0].note == "$10.00" and rs[0].end is None                # end == start in the API


def test_tribe_detect_requires_json():
    home = {"https://uniondocs.org/": "tribe/uniondocs_home.html"}
    api = "https://uniondocs.org/wp-json/tribe/events/v1/events?per_page=1"
    c, _ = detect("tribe", "https://uniondocs.org/", {**home, api: "tribe/uniondocs_events.json"})
    assert c.source == {"adapter": "tribe", "base_url": "https://uniondocs.org"}
    c, _ = detect("tribe", "https://uniondocs.org/", {**home, api: ("tribe/cinematheque_not_json.html", "text/html")})
    assert c is None


def test_ics_matches_tribe_and_detects():
    assert [(r.start, r.title[:12]) for r in rows("uniondocs-ics")] == [(r.start, r.title[:12]) for r in rows("uniondocs")]
    c, _ = detect("ics", "https://uniondocs.org/", {
        "https://uniondocs.org/": "tribe/uniondocs_home.html",
        "https://uniondocs.org/events/?ical=1": ("ics/uniondocs.ics", "text/calendar")})
    assert c.source == {"adapter": "ics", "url": "https://uniondocs.org/events/?ical=1"}


# ---------- squarespace ----------
def test_squarespace_epoch_ms():
    rs = rows("maysles")
    r = next(r for r in rs if r.title.startswith("A Home Worth"))
    assert r.start == "2026-09-29T19:00:00-04:00" and r.end == "2026-09-29T21:30:00-04:00"
    assert r.detail_url == "https://www.maysles.org/calendar/a-home-worth-fighting-for"


def test_squarespace_detect_skips_plain_pages():
    c, probe = detect("squarespace", "https://www.maysles.org/", {
        "https://www.maysles.org/": "squarespace/maysles_home.html",
        "https://www.maysles.org/maysles-calendar?format=json": "squarespace/maysles_calendar.json",
        "https://www.maysles.org/calendar?format=json": "squarespace/maysles_events.json"})
    assert c.source == {"adapter": "squarespace", "base_url": "https://www.maysles.org", "collection": "calendar"}


# ---------- alamo / my calendar / eventive / spektrix / jsonld ----------
def test_alamo_one_cinema_of_a_market():
    rs = rows("alamo-lower-manhattan")
    assert rs and all(r.screen.startswith("Screen ") for r in rs)
    market = VenueConfig(id="alamo-nyc", name="Alamo NYC", source={"adapter": "alamo", "market": "nyc"})
    everything = build_scraper(market, client=object()).parse(load_fixture(P, DEMO["alamo-lower-manhattan"].extra["fixture"]).pages)
    assert len(everything) > len(rs) and any(r.screen.startswith("Lower Manhattan · ") for r in everything)


def test_alamo_detect_theater_url():
    c, _ = detect("alamo", "https://drafthouse.com/nyc/theater/lower-manhattan", {
        "https://drafthouse.com/nyc/theater/lower-manhattan": "alamo/nyc_home.html",
        "https://drafthouse.com/s/mother/v2/schedule/market/nyc": "alamo/nyc_schedule.json"})
    assert c.source == {"adapter": "alamo", "market": "nyc", "cinema_id": "2103"}


def test_my_calendar_description_metadata_and_detect():
    r = rows("trylon")[0]
    assert (r.title, r.director, r.year, r.runtime_min, r.language) == ("Je Tu Il Elle", "Chantal Akerman", 1975, 86, "French")
    assert r.start == "2026-09-28T19:00:00-05:00"                      # Minneapolis
    c, _ = detect("wp-my-calendar", "https://www.trylon.org/", {
        "https://www.trylon.org/": "wp_my_calendar/trylon_home.html",
        "https://www.trylon.org/wp-json/my-calendar/v1/events": "wp_my_calendar/trylon_events.json"})
    assert c.source == {"adapter": "wp-my-calendar", "base_url": "https://www.trylon.org"}


def test_eventive_parse_and_key_from_tenant_bundle():
    r = rows("cornell")[0]
    assert (r.title, r.director, r.year, r.runtime_min) == ("Thelma & Louise: New Student Movie Night!", "Ridley Scott", 1991, 130)
    assert r.detail_url == "https://cornellcinema.eventive.org/schedule/6a70d8c97888c1f2afd0237e"
    c, probe = detect("eventive", "https://cornellcinema.eventive.org/", {
        "https://cornellcinema.eventive.org/": "eventive/cornell_home.html",
        "https://cornellcinema.eventive.org/cornellcinema.04b45b24c293d18f5aa0.js": "eventive/cornell_tenant.js"})
    assert c.source == {"adapter": "eventive", "bucket": "6a4fa3acb024f1f9ffa9cb70",
                        "api_key": "e4db526c61158d3e96a154c5f2a09eb0", "site": "cornellcinema"}
    assert "eventive_public_key" in probe.hints


def test_eventive_not_detected_on_calendar_without_link():
    c, _ = detect("eventive", "https://nwfilmforum.org/calendar/", {
        "https://nwfilmforum.org/calendar/": "eventive/nwff_calendar.html"})
    assert c is None


def test_spektrix_instances():
    events = json.loads((P / "spektrix/tyneside_events_filtered.json").read_text())
    inst_page = RawPage("https://system.spektrix.com/tynesidecinema/api/v3/events/612201ALRTSLQMVLDPBMCBDBVVDGCBCLH/instances",
                        (P / "spektrix/tyneside_instances.json").read_text(), "2026-08-20T10:00:00Z", "json")
    events.append({"id": "612201ALRTSLQMVLDPBMCBDBVVDGCBCLH", "name": "Instance Owner", "duration": 100})
    ev_page = RawPage("https://system.spektrix.com/tynesidecinema/api/v3/events", json.dumps(events), "2026-08-20T10:00:00Z", "json")
    v = VenueConfig(id="tyneside", name="Tyneside", timezone="Europe/London", source={"adapter": "spektrix", "client": "tynesidecinema"})
    rs = build_scraper(v, client=object()).parse([ev_page, inst_page])
    assert len(rs) == 13 and rs[0].start == "2026-08-21T15:10:00+01:00" and rs[0].runtime_min == 100
    probe = SiteProbe.offline("https://example.org/", {"https://example.org/": ProbeResponse(
        "https://example.org/", 200, "text/html", '<a href="https://system.spektrix.com/tynesidecinema/website/EventDetails.aspx">x</a>')}).start()
    assert get_adapter_class("spektrix").detect(probe).source == {"adapter": "spektrix", "client": "tynesidecinema"}


def test_jsonld_graph_and_references():
    bam = rows("bam-jsonld")
    assert [r.title for r in bam] == ["Tony"] * 3                       # " - Mon, Sep 28 at 9PM" removed
    brattle = rows("brattle-jsonld")[0]
    assert (brattle.title, brattle.director, brattle.year) == ("Elements of Cinema: Midnight", "Mitchell Leisen", 1939)
    assert brattle.ticket_url == "https://brattlefilm.org/purchase/1713201/"


@pytest.mark.parametrize("page,expected", [("jsonld/vidiots_creepshow.html", 1), ("jsonld/filmforum_home_empty_dates.html", 0)])
def test_jsonld_detect_requires_real_dates(page, expected):
    c, _ = detect("jsonld", "https://example.org/film", {"https://example.org/film": page})
    assert (c is not None) == bool(expected)
