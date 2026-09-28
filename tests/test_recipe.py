"""The recipe interpreter, checked against the hand-written parsers on the same fixtures, plus
the smaller primitives (URL templates, date kinds, validation)."""
from datetime import date
from pathlib import Path

import pytest

from scraper.adapters.recipe import (RecipeError, check_recipe, load_recipe, page_context, page_urls, parse_date,
                                     run_recipe, template_regex)
from scraper.base import dedupe
from scraper.contract import load_fixture
from scraper.models import RawPage, VenueConfig
from scraper.normalize import zone
from scraper.registry import VENUES_FILE, build_scraper, load_venues

FIXTURES = Path(__file__).parent / "fixtures"
NY = zone("America/New_York")
VENUES = {v.id: v for v in load_venues(VENUES_FILE)}


def both(venue_id):
    fx = load_fixture(FIXTURES / venue_id)
    custom = {s.id: s.to_dict() for s in dedupe(build_scraper(VENUES[venue_id], client=object()).parse(fx.pages))}
    recipe = {s.id: s.to_dict() for s in dedupe(run_recipe(load_recipe(venue_id), fx.pages, venue_id, NY).screenings)}
    return custom, recipe


def test_anthology_recipe_equals_custom_parser():
    custom, recipe = both("anthology")
    assert len(custom) == 166 and custom == recipe                    # every field of every screening


def test_metrograph_recipe_equals_custom_parser_except_notes():
    custom, recipe = both("metrograph")
    assert custom.keys() == recipe.keys() and len(custom) == 164
    # notes come from per-day sentences in film descriptions and sold-out classes: custom-only logic
    strip = lambda d: {k: {f: v for f, v in s.items() if f != "note"} for k, s in d.items()}
    assert strip(custom) == strip(recipe)


def test_recipe_adapter_runs_like_any_source():
    v = VenueConfig(id="anthology", name="AFA", source={"adapter": "recipe", "recipe": "anthology"})
    fx = load_fixture(FIXTURES / "anthology")
    s = build_scraper(v, client=object())
    assert len(dedupe(s.parse(fx.pages))) == 166 and not s.needs_browser


def test_page_urls_and_template_roundtrip():
    spec = {"url": "https://x.org/cal?month={month}&year={year}", "paging": {"kind": "monthly", "months": 3}}
    urls = page_urls(spec, date(2026, 11, 20))
    assert [u for u, _ in urls] == ["https://x.org/cal?month=11&year=2026", "https://x.org/cal?month=12&year=2026",
                                     "https://x.org/cal?month=1&year=2027"]
    recipe = {"pages": [spec]}
    ctx = page_context(recipe, RawPage(urls[2][0] + "#showing-1", "", "2026-11-20T00:00:00Z"))
    assert ctx == {"year": 2027, "month": 1}
    daily = {"url": "https://x.org/day/{date:%-m/%-d/%Y}", "paging": {"kind": "daily", "days": 2}}
    assert [u for u, _ in page_urls(daily, date(2026, 9, 28))] == ["https://x.org/day/9/28/2026", "https://x.org/day/9/29/2026"]
    assert page_context({"pages": [daily]}, RawPage("https://x.org/day/10/3/2026", "", "")) == {"year": 2026, "month": 10, "day": 3}
    assert template_regex("https://x.org/?y={year}").match("https://x.org/?y=2026")


def test_parse_date_fills_missing_parts():
    ref = date(2026, 12, 28)
    assert parse_date("Thursday, October  1", {"regex": r"\b(\d{1,2})\b", "format": "%d"}, {"year": 2026, "month": 10}, ref) == date(2026, 10, 1)
    assert parse_date("Sat Jan 2", {"format": "%a %b %d"}, {}, ref) == date(2027, 1, 2)       # no year: nearest, future-biased
    assert parse_date("2026-09-23", {"format": "%Y-%m-%d"}, {}, ref) == date(2026, 9, 23)
    assert parse_date("nonsense", {"format": "%Y-%m-%d"}, {}, ref) is None


HTML = """<div class="card"><time datetime="2026-10-02 19:30:00 -0400"></time><h2>Zola</h2><a href="/buy/1">tix</a></div>
<div class="card"><span class="d">Oct 3</span><h2>ALL CAPS TITLE</h2><span class="t">7pm, 9:15 PM</span></div>"""


def test_attr_date_with_and_without_time():
    recipe = {"pages": [{"url": "https://x.org/"}], "item": "div.card",
              "date": {"kind": "attr", "selector": "time, span.d", "attr": "datetime", "format": "%Y-%m-%d %H:%M:%S %z"},
              "fields": {"title": {"selector": "h2"}, "times": {"selector": "span.t"},
                         "ticket_url": {"selector": "a", "attr": "href"}},
              "post": {"title_case": "smart"}}
    rows = run_recipe(recipe, [RawPage("https://x.org/", HTML, "2026-09-28T16:00:00Z")], "x", NY).screenings
    assert [(r.start, r.title) for r in rows][:1] == [("2026-10-02T19:30:00-04:00", "Zola")]
    assert rows[0].ticket_url == "https://x.org/buy/1"
    # second card: its span.d has no datetime attribute -> date from text is not attempted with this spec
    recipe["date"] = {"kind": "attr", "selector": "span.d", "format": "%b %d"}
    rows = run_recipe(recipe, [RawPage("https://x.org/", HTML, "2026-09-28T16:00:00Z")], "x", NY).screenings
    assert [(r.start, r.title) for r in rows] == [("2026-10-03T19:00:00-04:00", "All Caps Title"),
                                                   ("2026-10-03T21:15:00-04:00", "All Caps Title")]


def test_schema_rejects_unknown_keys_and_missing_parts():
    assert check_recipe(load_recipe("anthology")) == []
    bad = {"pages": [{"url": "ftp://x"}], "item": "div", "fields": {"title": {"selector": "h2", "xpath": "//h2"}}}
    problems = check_recipe(bad)
    assert any("times" in p for p in problems) and any("xpath" in p for p in problems) and any("ftp" in p for p in problems)
    with pytest.raises(RecipeError):
        load_recipe(bad)
