"""The add-venue wizard end to end, offline: SiteProbe on saved pages, a fixture-backed HTTP client for the
trial run, and a fake Claude client for recipe generation."""
import json
import shutil
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml

from scraper import add as add_mod
from scraper import recipe_gen
from scraper.base import _Resp
from scraper.config import load_venues
from scraper.contract import check, load_fixture
from scraper.models import RawPage
from scraper.probe import SiteProbe

P = Path(__file__).parent / "fixtures" / "platforms"
ROOT = Path(__file__).parent.parent
TODAY = date(2026, 9, 28)


class FixtureClient:
    """Stands in for HttpClient: answers GETs from saved files, keyed by URL without the query string."""

    def __init__(self, table: dict):
        self.table = {k.split("?")[0].rstrip("/"): v for k, v in table.items()}
        self.calls = []

    def get(self, url, *, min_interval=0.0, params=None, transport="httpx", headers=None):
        self.calls.append(url)
        path = self.table.get(url.split("?")[0].rstrip("/"))
        if path is None:
            from scraper.base import ScrapeError
            raise ScrapeError(f"HTTP 404: {url}")
        return _Resp(200, (P / path).read_text(encoding="utf-8"), url)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A copy of venues.yaml plus empty fixture / test / hand-off directories; a fixed clock."""
    venues = tmp_path / "venues.yaml"
    shutil.copy(ROOT / "config" / "venues.yaml", venues)
    for d in ("fixtures", "tests", "handoff"):
        (tmp_path / d).mkdir()
    monkeypatch.setattr("scraper.base.now_utc_iso", lambda: "2026-09-28T16:00:00Z")
    monkeypatch.setattr("scraper.detect.now_utc_iso", lambda: "2026-09-28T16:00:00Z")
    monkeypatch.setattr(recipe_gen, "available", lambda: False)
    return tmp_path


def run_add(sandbox, name, url, pages, client_table=None, **kw):
    spec = {u: (P / f if isinstance(f, str) else (P / f[0], *f[1:])) for u, f in pages.items()}
    probe = SiteProbe.offline(url, spec)
    lines = []
    res = add_mod.add(name, url, probe=probe, client=FixtureClient(client_table or {}), today=TODAY,
                      venues_file=sandbox / "venues.yaml", fixtures=sandbox / "fixtures", tests_dir=sandbox / "tests",
                      handoff_root=sandbox / "handoff", run_after=False, render=kw.pop("render", lambda *_: None),
                      say=lines.append, lang=kw.pop("lang", "en"), **kw)
    return res, lines


def test_nitehawk_filmbot_zero_code(sandbox):
    res, lines = run_add(sandbox, "Nitehawk Williamsburg", "https://nitehawkcinema.com/williamsburg/", {
        "https://nitehawkcinema.com/williamsburg/": "filmbot/nitehawk_home.html",
        "https://nitehawkcinema.com/williamsburg/wp-json/nj/v1/showtime/listings": "filmbot/nitehawk_listings.json"},
        {"https://nitehawkcinema.com/williamsburg/wp-json/nj/v1/showtime/listings": "filmbot/nitehawk_listings.json"},
        region="NYC")
    assert (res["status"], res["adapter"], res["venue_id"]) == ("ok", "filmbot", "nitehawk-williamsburg")
    assert res["source"] == {"adapter": "filmbot", "base_url": "https://nitehawkcinema.com/williamsburg"}
    assert res["timezone"] == "America/New_York" and res["count"] > 50
    assert res["summary"].startswith("Parsed ") and len(res["sample"]) == 10
    # venues.yaml: appended, comments kept, loads, validates
    text = (sandbox / "venues.yaml").read_text()
    assert text.startswith("# 影院注册表") and "id: nitehawk-williamsburg" in text
    added = {v.id: v for v in load_venues(sandbox / "venues.yaml")}["nitehawk-williamsburg"]
    assert added.adapter == "filmbot" and added.region == "NYC" and added.color.startswith("#")
    # fixture + manifest the contract accepts; thin test shell
    fx = load_fixture(sandbox / "fixtures" / "nitehawk-williamsburg")
    from scraper.registry import build_scraper
    rows = build_scraper(added, client=object()).parse(fx.pages)
    assert not check(added, rows, fx.fetched_date)
    assert "check_venue(\"nitehawk-williamsburg\")" in (sandbox / "tests" / "test_nitehawk_williamsburg.py").read_text()


def test_roxy_veezi(sandbox):
    res, _ = run_add(sandbox, "Roxy Cinema", "https://www.roxycinemanewyork.com/", {
        "https://www.roxycinemanewyork.com/": "veezi/roxy_home.html"},
        {"https://ticketing.uswest.veezi.com/sessions": "veezi/roxy_sessions.html"})
    assert (res["status"], res["adapter"]) == ("ok", "veezi")
    assert res["region"] == "NYC"                                  # from the address on the page


def test_uniondocs_tribe_beats_ics(sandbox):
    api = "https://uniondocs.org/wp-json/tribe/events/v1/events"
    res, _ = run_add(sandbox, "UnionDocs", "https://uniondocs.org/", {
        "https://uniondocs.org/": "tribe/uniondocs_home.html",
        api + "?per_page=1": "tribe/uniondocs_events.json",
        "https://uniondocs.org/events/?ical=1": ("ics/uniondocs.ics", "text/calendar")},
        {api: "tribe/uniondocs_events.json", "https://uniondocs.org/events/": "ics/uniondocs.ics"})
    assert res["status"] == "ok" and res["adapter"] == "tribe"          # lower DETECT_ORDER wins the tie


@pytest.mark.parametrize("page", ["movingimage_cloudflare.html", "hollywoodtheatre_cloudflare.html",
                                  "musicbox_sucuri.html", "cleveland_sucuri.html"])
def test_blocked_sites_say_so(sandbox, page):
    url = "https://blocked.example.org/"
    res, lines = run_add(sandbox, "Blocked Cinema", url, {url: (f"blocked/{page}", "text/html", 403)})
    assert res["status"] == "blocked" and res["reason"] in ("cloudflare", "sucuri")
    assert "does not work around" in res["message"] and res["next_steps"]
    assert not (sandbox / "handoff" / "blocked-cinema").exists()
    assert "blocked-cinema" not in (sandbox / "venues.yaml").read_text()


def test_blocked_even_with_http_200(sandbox):
    url = "https://blocked.example.org/"
    res, _ = run_add(sandbox, "Blocked", url, {url: "blocked/musicbox_sucuri.html"})
    assert res["status"] == "blocked"


def test_js_only_without_browser_is_no_showtimes(sandbox):
    url = "https://www.americancinematheque.com/now-showing/"
    res, _ = run_add(sandbox, "American Cinematheque", url, {url: "js_only/americancinematheque_now_showing.html"})
    assert res["status"] == "no_showtimes" and "schedule page" in res["message"]


def test_js_only_with_browser_hands_off_a_browser_recipe(sandbox):
    url = "https://www.americancinematheque.com/now-showing/"
    rendered = (P / "recipe" / "quad.html").read_text()                # any page with showtimes after JS
    res, _ = run_add(sandbox, "American Cinematheque", url, {url: "js_only/americancinematheque_now_showing.html"},
                     render=lambda *_: rendered, tz="America/Los_Angeles")
    assert (res["status"], res["reason"]) == ("needs_agent", "browser_recipe")
    out = sandbox / "handoff" / "american-cinematheque"
    brief = (out / "BRIEF.md").read_text()
    assert "render: browser" in brief and "America/Los_Angeles" in brief and "pages/rendered.html" in brief
    assert (out / "pages" / "rendered.html").exists() and json.loads((out / "detect.json").read_text())["needs_browser"]


def test_coolidge_agile_without_guid_hands_off_recipe(sandbox):
    res, _ = run_add(sandbox, "Coolidge Corner Theatre", "https://coolidge.org/", {
        "https://coolidge.org/": "agile/coolidge_home.html"}, lang="zh")
    assert res["status"] == "needs_agent" and "agile_no_feed_guid" in res["hints"]
    assert "GUID" in res["message"] and res["timezone"] == "America/New_York"
    vid = Path(res["handoff"]).name             # coolidge-corner-theatre-2: the real Coolidge is in venues.yaml
    assert vid.startswith("coolidge-corner-theatre")
    out = sandbox / "handoff" / vid
    brief = (out / "BRIEF.md").read_text()
    for must in (vid, f"scraper/recipes/{vid}.yaml", "\"date\"",
                 "kind: heading", "kind: container", "class BaseScraper", "@register(\"japansociety\")",
                 f"pytest tests/test_contract.py -k {vid}", "Do not work around CAPTCHAs",
                 f"delete `handoff/{vid}/`"):
        assert must in brief, must
    draft = yaml.safe_load((out / "venue.yaml").read_text())[0]
    assert draft["source"] == {"adapter": "recipe", "recipe": vid}
    assert list((out / "pages").glob("*.html"))


def test_dry_run_writes_nothing(sandbox):
    before = (sandbox / "venues.yaml").read_text()
    res, _ = run_add(sandbox, "Coolidge", "https://coolidge.org/", {"https://coolidge.org/": "agile/coolidge_home.html"},
                     dry_run=True)
    assert res["status"] == "needs_agent" and (sandbox / "venues.yaml").read_text() == before
    assert not any((sandbox / "handoff").iterdir())


# ---------------------------------------------------------------- recipe generation with a fake Claude
class FakeClaude:
    """client.beta.messages.create(...) returning queued JSON answers; records the conversation."""

    def __init__(self, answers):
        self.answers, self.requests = list(answers), []
        self.beta = self
        self.messages = self

    def create(self, **kw):
        self.requests.append(json.loads(json.dumps(kw)))          # snapshot: the caller keeps appending
        text = json.dumps(self.answers.pop(0))

        class Block:
            type = "text"

        b = Block()
        b.text = text

        class Resp:
            stop_reason = "end_turn"
            content = [b]
        return Resp()


ANTHOLOGY_URL = "https://www.anthologyfilmarchives.org/film_screenings/calendar?view=list&month=10&year=2026"


def test_llm_writes_recipe_after_feedback(sandbox, monkeypatch):
    monkeypatch.setattr("scraper.recipe_gen.SAVE_DIR", sandbox)
    good = (ROOT / "scraper" / "recipes" / "anthology.yaml").read_text()
    bad = good.replace('item: "div.film-showing"', 'item: "div.nothing-here"')
    fake = FakeClaude([{"recipe_yaml": bad, "notes": "first try"}, {"recipe_yaml": good, "notes": "fixed"}])
    res, _ = run_add(sandbox, "Anthology Film Archives", ANTHOLOGY_URL,
                     {ANTHOLOGY_URL: "../anthology/2026-10.html"}, use_llm=True, llm_client=fake, venue_id="afa")
    assert (res["status"], res["adapter"]) == ("ok", "recipe") and res["count"] > 50
    assert len(fake.requests) == 2
    feedback = fake.requests[1]["messages"][-1]["content"]
    assert "matched nothing" in feedback and "Fix the recipe" in feedback
    req = fake.requests[0]
    assert req["model"] == "claude-opus-5-5" and req["output_config"]["format"]["type"] == "json_schema"
    assert req["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in req["betas"]
    assert (sandbox / "afa.yaml").exists()
    added = {v.id: v for v in load_venues(sandbox / "venues.yaml")}["afa"]
    assert added.source == {"adapter": "recipe", "recipe": "afa"}


def test_llm_gives_up_after_three_rounds(sandbox):
    bad = {"recipe_yaml": "pages: []\nitem: x\nfields: {}", "notes": ""}
    fake = FakeClaude([bad, bad, bad, bad])
    res, _ = run_add(sandbox, "Anthology", ANTHOLOGY_URL, {ANTHOLOGY_URL: "../anthology/2026-10.html"},
                     use_llm=True, llm_client=fake)
    assert (res["status"], res["reason"]) == ("needs_agent", "llm_failed") and len(fake.requests) == 3


def test_judge_flags_wrong_years():
    recipe = yaml.safe_load((ROOT / "scraper" / "recipes" / "metrograph.yaml").read_text())
    page = RawPage("https://metrograph.com/nyc/", (ROOT / "tests/fixtures/metrograph/nyc.html").read_text(),
                   "2027-09-25T01:00:00Z")                           # a year later: every date is in the past
    v = recipe_gen.judge(recipe, [page], "mg", "America/New_York")
    assert not v.ok and any("dates are probably wrong" in p for p in v.problems)


# ---------------------------------------------------------------- CLI
def test_cli_help_and_verify_requires_args(capsys):
    with pytest.raises(SystemExit) as e:
        add_mod.main(["--help"])
    assert e.value.code == 0 and "--json" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        add_mod.main([])


def test_slug_and_short_names():
    assert add_mod.slugify("L'Alliance New York") == "lalliance-new-york"
    assert add_mod.slugify("The Brattle Theatre") == "brattle-theatre"
    assert add_mod.unique_id("roxy", {"roxy", "roxy-2"}) == "roxy-3"
    assert add_mod.short_name("Nitehawk Williamsburg") == "NW"


@pytest.mark.parametrize("url,page,state", [
    ("https://nitehawkcinema.com/williamsburg/", "filmbot/nitehawk_home.html", "NY"),   # JSON-LD streetAddress
    ("https://coolidge.org/", "agile/coolidge_home.html", "MA"),       # not NY, despite "New York" in blurbs
    ("https://www.trylon.org/", "wp_my_calendar/trylon_home.html", "MN"),
    ("https://gablescinema.com/", "agile/gables_home.html", "FL"),
    ("https://vidiotsfoundation.org/m", "jsonld/vidiots_creepshow.html", "CA"),
    ("https://www.maysles.org/", "squarespace/maysles_home.html", None),   # no address on the page: ask, don't guess
])
def test_state_from_the_sites_own_address(url, page, state):
    from scraper.detect import guess_state
    assert guess_state(SiteProbe.offline(url, {url: P / page}).start()) == state


def test_blocked_site_does_not_ask_for_a_time_zone(sandbox, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    url = "https://blocked.example.org/"
    asked = []
    res, _ = run_add(sandbox, "Blocked", url, {url: ("blocked/movingimage_cloudflare.html", "text/html", 403)},
                     ask=lambda q: asked.append(q) or "")
    assert res["status"] == "blocked" and not asked


def test_dry_run_does_not_point_at_a_brief_it_did_not_write(sandbox):
    res, lines = run_add(sandbox, "Coolidge", "https://coolidge.org/", {"https://coolidge.org/": "agile/coolidge_home.html"},
                         dry_run=True)
    assert res["region"] == "BOS" and "--dry-run" in res["next_steps"][0] and "handoff" not in res
