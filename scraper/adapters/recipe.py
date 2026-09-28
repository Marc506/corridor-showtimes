"""Declarative HTML recipes (ARCHITECTURE §5.7, PLATFORMS.md §11).

    source: {adapter: recipe, recipe: anthology}        # scraper/recipes/anthology.yaml
    source: {adapter: recipe, recipe: {pages: …, date: …, item: …, fields: …}}   # or inline

A recipe is data: which pages to fetch, where the date of each screening comes from, which node is one
programme, and how to read each field from it. It is small on purpose — the primitives below and nothing
else. A site that needs more (times without am/pm, one detail page per card) stays a custom module.

pages[]    url template ({year} {month} {day} {date:%Y-%m-%d}), paging {kind: none | monthly {months} |
           daily {days}}, render html | browser, stop_when_empty
date       kind: heading   — date headings interleaved with items, in document order (Anthology)
                 attr      — each item carries its own date (selector / attr inside the item)
                 container — items sit inside one container per day (Metrograph)
                 page      — one page per day; the date comes from the page URL
           selector, attr, regex (group 1), format (strftime; missing year / month come from the page URL,
           else the nearest date to the fetch day, biased to the future)
item       CSS selector of one programme
fields     title times director year runtime_min format language series screen note detail_url ticket_url
           and `meta` (named regex groups only). Each: selector | text_after | per_time, attr, regex
           (group 1, or named groups -> fields), strip_prefix, template ("{page_url}#{value}"), case: smart,
           parse: language. `times` collects every match: regex + format (default: the four forms below).
post       title_case: smart; detect_language: true (from the item's text)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import urljoin

import yaml
from bs4 import BeautifulSoup, NavigableString, Tag

from ..base import BaseScraper, RequestBudgetExceeded, ScrapeError
from ..models import RawPage, Screening
from ..normalize import (clean_text, end_from_runtime, iso, language_from_text, make_id, nearest_date,
                         normalize_format, smart_title, to_local, today_local)
from . import Candidate, register_adapter

RECIPES_DIR = Path(__file__).resolve().parent.parent / "recipes"
SCHEMA_FILE = RECIPES_DIR / "recipe.schema.json"
TIME_RE = r"(\d{1,2}(?::\d{2})?\s*[AaPp]\.?\s*[Mm]\.?|\b\d{1,2}:\d{2}\b)"
TIME_FORMATS = ["%I:%M %p", "%I:%M%p", "%I %p", "%I%p", "%H:%M"]
FIELDS = ["title", "director", "year", "runtime_min", "format", "language", "series", "screen", "note",
          "detail_url", "ticket_url"]
_DIRECTIVE = re.compile(r"%-?([a-zA-Z])")


class RecipeError(ValueError):
    pass


# ---------------------------------------------------------------- loading
def load_recipe(ref, lang: str | None = None) -> dict:
    """ref: recipe id (scraper/recipes/<id>.yaml), a path, or an inline dict. Validated against the schema."""
    if isinstance(ref, dict):
        recipe = ref
    else:
        path = Path(ref) if str(ref).endswith((".yaml", ".yml")) else RECIPES_DIR / f"{ref}.yaml"
        if not path.exists():
            raise RecipeError(f"recipe not found: {path}")
        recipe = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    problems = check_recipe(recipe)
    if problems:
        raise RecipeError("; ".join(problems))
    return recipe


def check_recipe(recipe: dict) -> list[str]:
    try:
        import jsonschema
    except ImportError:
        return []
    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    out = []
    for err in jsonschema.Draft202012Validator(schema).iter_errors(recipe):
        where = ".".join(str(p) for p in err.path) or "recipe"
        out.append(f"{where}: {err.message}")
    return out


# ---------------------------------------------------------------- page URLs
def page_urls(spec: dict, today: date) -> list[tuple[str, date | None]]:
    """(url, the date the URL stands for) for one pages[] entry."""
    paging = spec.get("paging") or {"kind": "none"}
    kind = paging.get("kind", "none")
    tpl = spec["url"]
    if kind == "monthly":
        out, y, m = [], today.year, today.month
        for _ in range(int(paging.get("months", 3))):
            d = date(y, m, 1)
            out.append((tpl.format(year=y, month=m, day=1, date=d), d))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return out
    if kind == "daily":
        return [(tpl.format(year=d.year, month=d.month, day=d.day, date=d), d)
                for d in (today + timedelta(days=i) for i in range(int(paging.get("days", 14))))]
    return [(tpl.format(year=today.year, month=today.month, day=today.day, date=today), None)]


def _strftime_regex(fmt: str) -> str:
    parts, last = [], 0
    for m in _DIRECTIVE.finditer(fmt):
        parts.append(re.escape(fmt[last:m.start()]))
        parts.append({"Y": r"\d{4}", "y": r"\d{2}", "m": r"\d{1,2}", "d": r"\d{1,2}", "b": r"[A-Za-z]{3}",
                      "B": r"[A-Za-z]+", "a": r"[A-Za-z]{3}", "A": r"[A-Za-z]+", "j": r"\d{1,3}"}.get(m.group(1), r".+?"))
        last = m.end()
    parts.append(re.escape(fmt[last:]))
    return "".join(parts)


def template_regex(tpl: str) -> re.Pattern:
    """'…?month={month}&year={year}' -> regex with named groups, to recover a page's date from its URL."""
    out, last = [], 0
    for m in re.finditer(r"\{(\w+)(?::([^}]*))?\}", tpl):
        out.append(re.escape(tpl[last:m.start()]))
        name, spec = m.group(1), m.group(2) or ""
        if name == "date":
            out.append(f"(?P<date>{_strftime_regex(spec or '%Y-%m-%d')})")
        elif name in ("year", "month", "day") and f"(?P<{name}>" not in "".join(out):
            out.append(rf"(?P<{name}>\d{{{4 if name == 'year' else '1,2'}}})")
        else:
            out.append(r"[^&#/]*")
        last = m.end()
    out.append(re.escape(tpl[last:]))
    return re.compile("^" + "".join(out) + "$")


def page_context(recipe: dict, page: RawPage) -> dict:
    """{year, month, day} the page URL stands for (from the pages[] templates), plus the fetch date."""
    ctx: dict = {}
    for spec in recipe.get("pages") or []:
        m = template_regex(spec["url"]).match(page.url.split("#")[0])
        if not m:
            continue
        g = m.groupdict()
        if g.get("date"):
            fmt = re.search(r"\{date:([^}]*)\}", spec["url"])
            try:
                d = datetime.strptime(g["date"], (fmt.group(1) if fmt else "%Y-%m-%d").replace("%-", "%")).date()
                ctx.update(year=d.year, month=d.month, day=d.day)
            except ValueError:
                pass
        for k in ("year", "month", "day"):
            if g.get(k):
                ctx[k] = int(g[k])
        break
    return ctx


# ---------------------------------------------------------------- dates and times
def parse_date(text: str, spec: dict, ctx: dict, ref: date) -> date | None:
    text = clean_text(text) or ""
    if spec.get("regex"):
        m = re.search(spec["regex"], text)
        if not m:
            return None
        text = m.group(1) if m.groups() else m.group(0)
    fmt = spec.get("format")
    if not fmt:
        return None
    directives = {m.group(1) for m in _DIRECTIVE.finditer(fmt)}
    try:
        parsed = datetime.strptime(re.sub(r"\s+", " ", text.strip()), fmt.replace("%-", "%"))
    except ValueError:
        return None
    day = parsed.day if directives & {"d", "j"} else ctx.get("day", 1)
    month = parsed.month if directives & {"m", "b", "B", "j"} else ctx.get("month")
    if directives & {"Y", "y"}:
        year = parsed.year
    elif ctx.get("year") and month is not None:
        year = ctx["year"]
    else:
        year = None
    if month is None:
        return None
    if year is None:
        return nearest_date(month, day, ref)
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_datetime_attr(text: str, spec: dict) -> datetime | None:
    """date.kind attr with a time in it: '2026-09-28 21:30:00 -0400' / ISO."""
    fmt = spec.get("format")
    text = clean_text(text) or ""
    if spec.get("regex") and (m := re.search(spec["regex"], text)):
        text = m.group(1) if m.groups() else m.group(0)
    try:
        return datetime.strptime(text, fmt) if fmt else datetime.fromisoformat(text)
    except ValueError:
        return None


def parse_time(text: str, formats: list[str]) -> time | None:
    t = re.sub(r"\s+", " ", text.strip().replace(".", "")).upper()
    for cand in (t, t.replace(" ", "")):
        for fmt in formats:
            try:
                return datetime.strptime(cand, fmt).time()
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------- fields
def _texts_after(node: Tag, selector: str) -> list[str]:
    """Bare text lines after the node `selector` (up to the next element other than <br>)."""
    anchor = node.select_one(selector)
    if anchor is None:
        return []
    out = []
    for sib in anchor.next_siblings:
        if isinstance(sib, Tag) and sib.name != "br":
            break
        if isinstance(sib, NavigableString):
            line = clean_text(str(sib))
            if line:
                out.append(line)
    return out


def _candidates(node: Tag, spec: dict, time_node: Tag | None) -> list[str]:
    if spec.get("per_time"):
        nodes = [time_node] if time_node is not None else []
    elif spec.get("text_after"):
        return _texts_after(node, spec["text_after"])
    elif spec.get("selector"):
        nodes = node.select(spec["selector"])[: None if spec.get("all") else 1]
    else:
        nodes = [node]
    out = []
    for n in nodes:
        v = n.get(spec["attr"]) if spec.get("attr") else n.get_text(" ")
        if isinstance(v, list):
            v = " ".join(v)
        if v:
            out.append(clean_text(v) or "")
    return [v for v in out if v]


def extract(node: Tag, spec: dict, time_node: Tag | None = None) -> tuple[str | None, dict]:
    """(value, named groups) for one field spec — the first candidate text that matches."""
    rx = re.compile(spec["regex"]) if spec.get("regex") else None
    for text in _candidates(node, spec, time_node):
        if spec.get("strip_prefix") and text.startswith(spec["strip_prefix"]):
            text = text[len(spec["strip_prefix"]):].strip()
        if spec.get("parse") == "language":
            lang = language_from_text(text)
            if lang:
                return lang, {}
            continue
        groups: dict = {}
        if rx:
            m = rx.search(text)
            if not m:
                continue
            groups = {k: v for k, v in m.groupdict().items() if v}
            text = m.group(1) if m.groups() and not m.groupdict() else (m.group(0) if not groups else text)
        value = clean_text(text)
        if spec.get("template") and value:
            value = spec["template"].format(value=value, page_url=spec.get("_page_url", ""))
        if spec.get("case") == "smart":
            value = smart_title(value)
        return value, groups
    return None, {}


def _int(v) -> int | None:
    m = re.match(r"\s*(\d+)", str(v or ""))
    return int(m.group(1)) if m else None


def coerce(fields: dict, page_url: str) -> dict:
    out = dict(fields)
    for k in ("year", "runtime_min"):
        out[k] = _int(out.get(k))
    if out.get("runtime_min") and not 1 <= out["runtime_min"] <= 600:
        out["runtime_min"] = None
    if out.get("format"):
        out["format"] = normalize_format(out["format"].strip(" .,"))
    for k in ("detail_url", "ticket_url"):
        if out.get(k):
            out[k] = urljoin(page_url, out[k])
    return out


# ---------------------------------------------------------------- the interpreter
@dataclass
class RecipeResult:
    screenings: list[Screening] = field(default_factory=list)
    items: int = 0                 # item nodes found
    items_with_times: int = 0      # of which at least one time parsed
    problems: list[str] = field(default_factory=list)


def _items_by_date(soup, recipe: dict, ctx: dict, ref: date):
    """Yield (item node, date or None) according to date.kind."""
    dspec = recipe.get("date") or {"kind": "attr"}
    kind = dspec.get("kind", "attr")
    item_sel = recipe["item"]
    if kind == "heading":
        heading_sel = dspec["selector"]
        current = None
        heads = set(map(id, soup.select(heading_sel)))
        for node in soup.select(f"{heading_sel}, {item_sel}"):
            if id(node) in heads:
                text = node.get(dspec["attr"]) if dspec.get("attr") else node.get_text(" ")
                current = parse_date(text or "", dspec, ctx, ref)
            else:
                yield node, current
    elif kind == "container":
        for box in soup.select(dspec["selector"]):
            text = box.get(dspec["attr"]) if dspec.get("attr") else box.get_text(" ")
            d = parse_date(text or "", dspec, ctx, ref)
            for node in box.select(item_sel):
                yield node, d
    elif kind == "page":
        d = date(ctx["year"], ctx["month"], ctx["day"]) if {"year", "month", "day"} <= ctx.keys() else None
        for node in soup.select(item_sel):
            yield node, d
    else:                                                   # attr: each item carries its date
        for node in soup.select(item_sel):
            yield node, None


def run_recipe(recipe: dict, pages: list[RawPage], venue_id: str, tz) -> RecipeResult:
    """Apply a recipe to fetched pages. Pure; used by the adapter, the recipe generator and tests."""
    res = RecipeResult()
    fields = recipe.get("fields") or {}
    dspec = recipe.get("date") or {"kind": "attr"}
    tspec = fields.get("times") or {}
    formats = [tspec["format"]] if tspec.get("format") else TIME_FORMATS
    post = recipe.get("post") or {}
    for page in pages:
        ctx = page_context(recipe, page)
        ref = datetime.fromisoformat(page.fetched_at.replace("Z", "+00:00")).astimezone(tz).date()
        soup = BeautifulSoup(page.body, "lxml")
        for node, day in _items_by_date(soup, recipe, ctx, ref):
            res.items += 1
            starts: list[tuple[datetime, Tag | None]] = []
            if dspec.get("kind", "attr") == "attr":
                sel = dspec.get("selector")
                holder = node.select_one(sel) if sel else node
                raw = (holder.get(dspec["attr"]) if dspec.get("attr") else holder.get_text(" ")) if holder else None
                if raw and re.search(r"%[HIM]|T\d", (dspec.get("format") or "") + raw[:20]):
                    if dt := parse_datetime_attr(raw, dspec):
                        starts.append((to_local(dt, tz), holder))
                elif raw:
                    day = parse_date(raw, dspec, ctx, ref)
            if not starts and day is not None:
                time_nodes = node.select(tspec["selector"]) if tspec.get("selector") else [node]
                rx = re.compile(tspec.get("regex") or TIME_RE)
                for tn in time_nodes:
                    text = tn.get(tspec["attr"]) if tspec.get("attr") else tn.get_text(" ")
                    for m in rx.finditer(clean_text(text) or ""):
                        tm = parse_time(m.group(1) if m.groups() else m.group(0), formats)
                        if tm is not None:
                            starts.append((to_local(datetime.combine(day, tm), tz), tn))
            if not starts:
                continue
            res.items_with_times += 1
            base: dict = {}
            for name, spec in fields.items():
                if name == "times" or spec.get("per_time"):
                    continue
                value, groups = extract(node, {**spec, "_page_url": page.url})
                for k, v in groups.items():
                    base.setdefault(k, v)
                if name != "meta" and value is not None:
                    base[name] = value
            title = base.get("title")
            if title and post.get("title_case") == "smart":
                title = smart_title(title)
            if not title:
                continue
            if post.get("detect_language") and not base.get("language"):
                base["language"] = language_from_text(node.get_text(" "))
            for start, tn in starts:
                row = dict(base)
                for name, spec in fields.items():
                    if spec.get("per_time"):
                        value, groups = extract(node, {**spec, "_page_url": page.url}, time_node=tn)
                        row.update({k: v for k, v in groups.items() if v})
                        if value is not None:
                            row[name] = value
                row = coerce(row, page.url)
                start_s = iso(start, tz)
                res.screenings.append(Screening(
                    id=make_id(venue_id, start_s, title), venue_id=venue_id, title=title, start=start_s,
                    day=start_s[:10], end=end_from_runtime(start, row.get("runtime_min")),
                    **{k: row.get(k) for k in FIELDS if k != "title"}, scraped_at=page.fetched_at))
    return res


@register_adapter("recipe")
class RecipeAdapter(BaseScraper):
    PARAMS = {"recipe": object}
    DETECT_ORDER = 90

    @property
    def recipe(self) -> dict:
        if not hasattr(self, "_recipe"):
            self._recipe = load_recipe(self.params["recipe"])
        return self._recipe

    @property
    def needs_browser(self) -> bool:
        return any(p.get("render") == "browser" for p in self.recipe.get("pages") or [])

    def fetch(self) -> list[RawPage]:
        pages = []
        today = today_local(self.tz)
        for spec in self.recipe["pages"]:
            for url, _ in page_urls(spec, today):
                try:
                    page = self.browser_page(url) if spec.get("render") == "browser" else self.get_page(url)
                except RequestBudgetExceeded:
                    return pages
                pages.append(page)
                if spec.get("stop_when_empty") and not BeautifulSoup(page.body, "lxml").select_one(self.recipe["item"]):
                    break
        if not pages:
            raise ScrapeError("recipe produced no pages")
        return pages

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        return run_recipe(self.recipe, pages, self.venue.id, self.tz).screenings
