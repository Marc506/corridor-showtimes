"""Load and check config/venues.yaml.

Two shapes are accepted:
  * v2: ``{version: 2, venues: [...]}`` with ``source:`` / ``fallback:`` / ``region`` / ``timezone``;
  * v1: a bare list with ``scraper:``, ``screenslate_nid:`` and ``city:``. Each v1 entry is converted in
    memory to ``source: {adapter: custom, module: <scraper>}``, ``fallback: {adapter: screenslate,
    nid: <screenslate_nid>}`` and ``region: <city>``, so old files keep working unchanged.

Problems are reported as one plain-language line per problem ("Venue #3 (foo) is missing `name`"),
never as a validator traceback.
"""
from __future__ import annotations

import json
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from .i18n import current_lang, t
from .models import VenueConfig

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_FILE = ROOT / "config" / "venues.schema.json"
SOURCES_DIR = Path(__file__).resolve().parent / "sources"


class ConfigError(ValueError):
    def __init__(self, problems: list[str], lang: str | None = None):
        self.problems = problems
        head = t("cfg.header", lang, n=len(problems)) if len(problems) > 1 else ""
        super().__init__("\n".join(([head] if head else []) + [f"  - {p}" if head else p for p in problems]))


def v1_to_v2(entry: dict) -> dict:
    """One v1 list item -> v2 venue dict (unknown keys pass through)."""
    d = dict(entry)
    if "source" not in d and d.get("scraper"):
        d["source"] = {"adapter": "custom", "module": d.pop("scraper")}
    else:
        d.pop("scraper", None)
    if "fallback" not in d:
        nid = d.pop("screenslate_nid", None)
        d["fallback"] = {"adapter": "screenslate", "nid": nid} if nid else None
    else:
        d.pop("screenslate_nid", None)
    if "region" not in d and "city" in d:
        d["region"] = d.pop("city")
    else:
        d.pop("city", None)
    return d


def read_raw(path: Path, lang: str | None = None) -> tuple[int, list[dict]]:
    """(format version, v2-shaped venue dicts) — raises ConfigError on unreadable files."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError([t("cfg.not_found", lang, path=path)]) from None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        raise ConfigError([t("cfg.yaml", lang, path=Path(path).name, line=(mark.line + 1) if mark else "?",
                             problem=getattr(e, "problem", None) or str(e))]) from None
    if data is None:
        return 2, []
    if isinstance(data, list):
        return 1, [v1_to_v2(d) if isinstance(d, dict) else d for d in data]
    if isinstance(data, dict) and "venues" in data:
        if data.get("version") != 2:
            raise ConfigError([t("cfg.version", lang)])
        return 2, list(data.get("venues") or [])
    raise ConfigError([t("cfg.top", lang)])


def _where(i: int, venue, lang) -> str:
    label = ""
    if isinstance(venue, dict) and venue.get("id"):
        label = f"（{venue['id']}）" if current_lang(lang) == "zh" else f" ({venue['id']})"
    return t("cfg.venue", lang, n=i + 1, label=label)


def _schema_problems(venues: list, lang) -> list[str]:
    try:
        import jsonschema
    except ImportError:                                  # validation is a nicety, not a requirement
        return []
    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    problems = []
    for err in sorted(validator.iter_errors({"version": 2, "venues": venues}), key=lambda e: list(e.path)):
        path = list(err.path)
        if len(path) < 2 or path[0] != "venues":
            problems.append(err.message)
            continue
        i, venue = path[1], venues[path[1]]
        where = _where(i, venue, lang)
        field = ".".join(str(p) for p in path[2:])
        if err.validator == "required":
            missing = err.message.split("'")[1] if "'" in err.message else err.message
            problems.append(t("cfg.missing", lang, where=where, field=f"{field}.{missing}" if field else missing))
        elif err.validator == "type":
            expected = err.validator_value if isinstance(err.validator_value, list) else [err.validator_value]
            words = " / ".join(t(f"type.{x}", lang) for x in expected)
            problems.append(t("cfg.type", lang, where=where, field=field, expected=words))
        elif err.validator == "pattern":
            problems.append(t("cfg.pattern", lang, where=where, field=field, value=err.instance))
        elif err.validator in ("minimum", "maximum", "minLength", "const"):
            problems.append(t("cfg.range", lang, where=where, field=field, value=err.instance))
        elif err.validator == "oneOf" and path[2:] == ["fallback"]:
            problems.append(t("cfg.missing", lang, where=where, field="fallback.adapter"))
        else:
            problems.append(t("cfg.other", lang, where=where, field=field, detail=err.message))
    return problems


def _semantic_problems(venues: list[dict], lang) -> list[str]:
    from .adapters import get_adapter_class, known_adapters
    problems, seen = [], set()
    for i, v in enumerate(venues):
        if not isinstance(v, dict):
            continue
        where = _where(i, v, lang)
        if v.get("id") in seen:
            problems.append(t("cfg.dup_id", lang, where=where, id=v["id"]))
        seen.add(v.get("id"))
        tz = v.get("timezone")
        if tz:
            try:
                ZoneInfo(tz)
            except (ZoneInfoNotFoundError, ValueError):
                problems.append(t("cfg.bad_tz", lang, where=where, tz=tz))
        for key in ("source", "fallback"):
            ref = v.get(key)
            if not isinstance(ref, dict) or not ref.get("adapter"):
                continue
            name = ref["adapter"]
            if name == "custom":
                module = ref.get("module")
                if not module:
                    problems.append(t("cfg.bad_params", lang, where=where, field=key, params="module"))
                elif not (SOURCES_DIR / f"{module}.py").exists():
                    problems.append(t("cfg.bad_module", lang, where=where, module=module))
                continue
            try:
                cls = get_adapter_class(name)
            except KeyError:
                problems.append(t("cfg.bad_adapter", lang, where=where, field=key, adapter=name,
                                  known=", ".join(["custom"] + known_adapters())))
                continue
            missing = [p for p in cls.PARAMS if ref.get(p) in (None, "")]
            if missing:
                problems.append(t("cfg.bad_params", lang, where=where, field=key, params=", ".join(missing)))
    return problems


def check_venues(venues: list, lang: str | None = None) -> list[str]:
    return _schema_problems(venues, lang) or _semantic_problems(venues, lang)


def load_venues(path: Path, lang: str | None = None) -> list[VenueConfig]:
    _, venues = read_raw(path, lang)
    problems = check_venues(venues, lang)
    if problems:
        raise ConfigError(problems, lang)
    return [VenueConfig.from_dict(d) for d in venues]
