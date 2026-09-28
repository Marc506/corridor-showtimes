"""Generate or repair a recipe with Claude (optional; needs an Anthropic API key).

Why once-per-site generation instead of asking a model on every run: a recipe is data that can be tested
offline, diffed, and fixed by hand; per-run extraction would cost money per venue per run and would not
be reproducible (ARCHITECTURE §5.7).

Loop (at most MAX_ROUNDS):
  1. send the page (scripts/styles removed, cut to ~60K characters), the recipe schema, the date-shape
     notes from PLATFORMS.md §11 and a real example recipe;
  2. the model answers with JSON {"recipe_yaml": …, "notes": …} (structured output);
  3. the interpreter runs the recipe on the same page; the result is judged by `judge()`;
  4. the verdict (count, three sample rows, what is wrong) goes back as the next user turn.

The key comes from ANTHROPIC_API_KEY or config/anthropic_key.txt (gitignored). Without it,
`available()` is False and callers go straight to the agent hand-off (scraper/handoff.py).
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from .adapters.recipe import RECIPES_DIR, SCHEMA_FILE, RecipeError, check_recipe, run_recipe
from .models import RawPage, Screening
from .normalize import zone

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
KEY_FILE = ROOT / "config" / "anthropic_key.txt"
MODEL = "claude-opus-5-5"
MAX_ROUNDS = 3
PAGE_CHARS = 60_000
MIN_TIMED_SHARE = 0.8
SAVE_DIR = RECIPES_DIR                     # where accepted recipes are written

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "recipe_yaml": {"type": "string", "description": "The complete recipe as YAML"},
        "notes": {"type": "string", "description": "One or two sentences on how the page is structured"},
    },
    "required": ["recipe_yaml", "notes"],
    "additionalProperties": False,
}

SYSTEM = """You write scraping recipes for a cinema showtime aggregator. A recipe is a small YAML \
document interpreted by a fixed engine; you cannot add features to the engine, only use the keys in the \
JSON Schema you are given. Read the page HTML, find the repeated node that represents one programme \
(film or event), find where its date and showtimes live, and write the recipe. Prefer stable class \
names over positional selectors. If the page shows a date only as a heading above a group of items, use \
date.kind heading; if each item carries its own date, attr; if items are grouped in one container per \
day with the date in an attribute, container; if the page covers one day chosen by the URL, page. \
When a date has no year, give a format without %Y — the engine fills the year. Answer with the JSON \
object only."""


def api_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key and KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
    return key or None


def available() -> bool:
    if not api_key():
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def slim_html(html: str, limit: int = PAGE_CHARS) -> str:
    html = re.sub(r"<(script|style|noscript|svg|template)\b.*?</\1>", "", html, flags=re.S | re.I)
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    html = re.sub(r"\s+", " ", html)
    return html[:limit]


def shapes_notes() -> str:
    """PLATFORMS.md §11 (the four date shapes), for the prompt."""
    text = (ROOT / "PLATFORMS.md").read_text(encoding="utf-8") if (ROOT / "PLATFORMS.md").exists() else ""
    m = re.search(r"## 11\..*?(?=\n## 12\.)", text, re.S)
    return m.group(0) if m else ""


# ------------------------------------------------------------------ judging a recipe
@dataclass
class Verdict:
    ok: bool
    screenings: list[Screening] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def feedback(self) -> str:
        sample = [f"{s.start}  {s.title}" + (f"  ({s.director}, {s.year})" if s.director or s.year else "")
                  for s in sorted(self.screenings, key=lambda s: s.start)[:3]]
        return (f"The engine parsed {len(self.screenings)} screenings.\n"
                + ("Sample:\n" + "\n".join(sample) + "\n" if sample else "")
                + ("Problems:\n- " + "\n- ".join(self.problems) if self.problems else "No problems found."))


def judge(recipe: dict, pages: list[RawPage], venue_id: str, tz_name: str, horizon_days: int = 60) -> Verdict:
    """Success = at least one future screening, >= 80% of item nodes yield a time, dates in a sane window."""
    problems = check_recipe(recipe)
    if problems:
        return Verdict(False, [], [f"schema: {p}" for p in problems[:8]])
    try:
        res = run_recipe(recipe, pages, venue_id, zone(tz_name))
    except Exception as e:  # noqa: BLE001 — a bad selector or regex is feedback, not a crash
        return Verdict(False, [], [f"the engine failed: {type(e).__name__}: {e}"])
    rows = res.screenings
    fetched = datetime.fromisoformat(pages[0].fetched_at.replace("Z", "+00:00")).astimezone(zone(tz_name)).date()
    lo, hi = fetched - timedelta(days=1), fetched + timedelta(days=horizon_days + 60)
    future = [s for s in rows if lo <= date.fromisoformat(s.day) <= hi]
    if res.items == 0:
        problems.append(f"the item selector {recipe.get('item')!r} matched nothing")
    elif res.items_with_times < MIN_TIMED_SHARE * res.items:
        problems.append(f"only {res.items_with_times} of {res.items} item nodes produced a showtime "
                        f"(need {int(MIN_TIMED_SHARE * 100)}%) — the item selector may be too broad, or the "
                        "date/time rules miss some items")
    if rows and not future:
        problems.append(f"no screening falls between {lo} and {hi}; the dates are probably wrong "
                        f"(first parsed date {min(s.day for s in rows)})")
    far = [s for s in rows if date.fromisoformat(s.day) > hi]
    if len(far) > 0.1 * max(len(rows), 1):
        problems.append(f"{len(far)} screenings are dated after {hi} — check the year handling")
    if not rows and res.items:
        problems.append("items were found but no screening came out — check title and times")
    untitled = [s for s in rows if len(s.title) > 150]
    if untitled:
        problems.append("some titles are very long; the title selector probably covers a whole card")
    return Verdict(ok=bool(future) and not problems, screenings=rows, problems=problems)


# ------------------------------------------------------------------ the model loop
def _prompt(name: str, url: str, pages: list[RawPage], tz_name: str) -> str:
    example = (RECIPES_DIR / "anthology.yaml").read_text(encoding="utf-8")
    parts = [f"Cinema: {name}\nSchedule URL: {url}\nTime zone: {tz_name}\n",
             "Recipe JSON Schema:\n" + SCHEMA_FILE.read_text(encoding="utf-8"),
             "Where dates live on cinema pages (the four shapes):\n" + shapes_notes(),
             "A real recipe (Anthology Film Archives):\n" + example]
    for i, p in enumerate(pages[:2]):
        parts.append(f"Page {i + 1}: {p.url}\n" + slim_html(p.body))
    return "\n\n".join(parts)


def _ask(client, messages: list[dict]) -> dict | None:
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        messages=messages,
        thinking={"type": "adaptive"},
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        log.warning("recipe generation declined by the model")
        return None
    text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), "")
    try:
        return json.loads(text)
    except ValueError:
        return None


@dataclass
class Generation:
    recipe: dict | None
    verdict: Verdict | None
    rounds: list[dict] = field(default_factory=list)       # [{recipe_yaml, notes, problems}]


def generate(name: str, url: str, pages: list[RawPage], venue_id: str, tz_name: str, *,
             horizon_days: int = 60, client=None, previous: dict | None = None,
             max_rounds: int = MAX_ROUNDS) -> Generation:
    """Write (or, given `previous`, repair) a recipe for `pages`. client: an anthropic.Anthropic (tests pass a fake)."""
    if client is None:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key())
    content = _prompt(name, url, pages, tz_name)
    if previous is not None:
        content += ("\n\nThis recipe used to work on the site but no longer does; repair it:\n"
                    + yaml.safe_dump(previous, sort_keys=False, allow_unicode=True))
    messages: list[dict] = [{"role": "user", "content": content}]
    gen = Generation(None, None)
    for _ in range(max_rounds):
        answer = _ask(client, messages)
        if answer is None:
            break
        messages.append({"role": "assistant", "content": json.dumps(answer)})
        try:
            recipe = yaml.safe_load(answer.get("recipe_yaml") or "")
        except yaml.YAMLError as e:
            recipe, verdict = None, Verdict(False, [], [f"recipe_yaml is not valid YAML: {e}"])
        else:
            verdict = judge(recipe, pages, venue_id, tz_name, horizon_days) if isinstance(recipe, dict) else \
                Verdict(False, [], ["recipe_yaml must be a YAML mapping"])
        gen.rounds.append({"recipe_yaml": answer.get("recipe_yaml"), "notes": answer.get("notes"),
                           "problems": verdict.problems, "count": len(verdict.screenings)})
        if verdict.ok:
            gen.recipe, gen.verdict = recipe, verdict
            return gen
        gen.verdict = verdict
        messages.append({"role": "user", "content": verdict.feedback() + "\n\nFix the recipe and answer again."})
    return gen


def save_recipe(venue_id: str, recipe: dict, header: str = "") -> Path:
    path = SAVE_DIR / f"{venue_id}.yaml"
    text = yaml.safe_dump(recipe, sort_keys=False, allow_unicode=True, width=120)
    path.write_text((header + "\n" if header else "") + text, encoding="utf-8")
    return path


__all__ = ["available", "generate", "judge", "save_recipe", "Generation", "Verdict", "RecipeError"]
