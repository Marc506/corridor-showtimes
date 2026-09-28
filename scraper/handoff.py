"""Agent hand-off package for a venue the wizard could not finish (ARCHITECTURE §5.7).

    handoff/<id>/BRIEF.md     self-contained task for any coding agent (templates/BRIEF.md.j2)
    handoff/<id>/detect.json  what detection tried and saw
    handoff/<id>/pages/*.html the fetched pages (and the browser-rendered one, if any)
    handoff/<id>/venue.yaml   the venue entry, source still to be decided
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from .adapters.recipe import RECIPES_DIR, SCHEMA_FILE
from .contract import FIELD_DOCS

ROOT = Path(__file__).resolve().parent.parent
HANDOFF_DIR = ROOT / "handoff"
TEMPLATE = ROOT / "templates" / "BRIEF.md.j2"


def _page_name(url: str, i: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", re.sub(r"^https?://", "", url.lower())).strip("-")[:60]
    return f"{i:02d}-{slug or 'page'}.html"


def render_brief(venue: dict, url: str, why: str, needs_browser: bool = False, first_page: str = "00-page.html") -> str:
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
    env = Environment(loader=FileSystemLoader(str(TEMPLATE.parent)), undefined=StrictUndefined,
                      keep_trailing_newline=True)
    return env.get_template(TEMPLATE.name).render(
        venue=venue, url=url, why=why, needs_browser=needs_browser, first_page=first_page,
        fields=FIELD_DOCS,
        recipe_schema=SCHEMA_FILE.read_text(encoding="utf-8").strip(),
        example_heading=(RECIPES_DIR / "anthology.yaml").read_text(encoding="utf-8").strip(),
        example_container=(RECIPES_DIR / "metrograph.yaml").read_text(encoding="utf-8").strip(),
        example_source=(ROOT / "scraper" / "sources" / "japansociety.py").read_text(encoding="utf-8").strip(),
    )


def write_handoff(venue: dict, url: str, detection, why: str, root: Path | None = None) -> Path:
    """venue: the draft venues.yaml entry (dict, v2 shape)."""
    out = (root or HANDOFF_DIR) / venue["id"]
    pages_dir = out / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    names = []
    for i, r in enumerate(detection.probe.pages):
        name = _page_name(r.final_url or r.url, i)
        (pages_dir / name).write_text(r.text, encoding="utf-8")
        names.append(name)
    if detection.browser_html:
        (pages_dir / "rendered.html").write_text(detection.browser_html, encoding="utf-8")
        names.insert(0, "rendered.html")
    (out / "detect.json").write_text(json.dumps(detection.evidence(), ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "venue.yaml").write_text(
        "# Draft entry for config/venues.yaml — replace source: once a recipe or module works.\n"
        + yaml.safe_dump([venue], sort_keys=False, allow_unicode=True), encoding="utf-8")
    full = {"max_requests_per_run": 20, "rate_limit_s": 2, "region": "", **venue}
    (out / "BRIEF.md").write_text(render_brief(full, url, why, detection.needs_browser,
                                               names[0] if names else "00-page.html"), encoding="utf-8")
    return out
