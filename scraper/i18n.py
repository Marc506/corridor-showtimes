"""Bilingual (zh / en) messages for everything a non-programmer reads: config errors, the add-venue
wizard, Issue comments. Tracebacks go to the log, never into these strings."""
from __future__ import annotations

import os

MESSAGES: dict[str, dict[str, str]] = {
    # --- venues.yaml ---
    "cfg.not_found": {"zh": "找不到配置文件 {path}", "en": "Config file not found: {path}"},
    "cfg.yaml": {"zh": "{path} 不是合法的 YAML（第 {line} 行附近）：{problem}",
                 "en": "{path} is not valid YAML (near line {line}): {problem}"},
    "cfg.top": {"zh": "venues.yaml 的最外层应该是影院列表，或 `version: 2` 加 `venues:` 列表",
                "en": "venues.yaml must be a list of venues, or `version: 2` with a `venues:` list"},
    "cfg.version": {"zh": "venues.yaml 的 version 只能是 2（或不写，表示旧格式）",
                    "en": "venues.yaml `version` must be 2 (or absent for the old format)"},
    "cfg.header": {"zh": "venues.yaml 有 {n} 处问题：", "en": "venues.yaml has {n} problem(s):"},
    "cfg.venue": {"zh": "第 {n} 家影院{label}", "en": "Venue #{n}{label}"},
    "cfg.missing": {"zh": "{where}缺少 {field}", "en": "{where} is missing `{field}`"},
    "cfg.type": {"zh": "{where}的 {field} 应该是{expected}", "en": "{where}: `{field}` should be {expected}"},
    "cfg.pattern": {"zh": "{where}的 {field} 格式不对（{value}）", "en": "{where}: `{field}` has the wrong format ({value})"},
    "cfg.range": {"zh": "{where}的 {field} 超出允许范围（{value}）", "en": "{where}: `{field}` is out of range ({value})"},
    "cfg.other": {"zh": "{where}：{field} {detail}", "en": "{where}: `{field}` {detail}"},
    "cfg.dup_id": {"zh": "{where}的 id「{id}」与前面的影院重复", "en": "{where}: id '{id}' is used twice"},
    "cfg.bad_tz": {"zh": "{where}的 timezone「{tz}」不是有效的时区名（例如 America/Los_Angeles）",
                   "en": "{where}: timezone '{tz}' is not a valid zone name (e.g. America/Los_Angeles)"},
    "cfg.bad_adapter": {"zh": "{where}的 {field}.adapter「{adapter}」不存在；可用：{known}",
                        "en": "{where}: {field}.adapter '{adapter}' does not exist; available: {known}"},
    "cfg.bad_module": {"zh": "{where}的 source.module「{module}」没有对应的 scraper/sources/{module}.py",
                       "en": "{where}: source.module '{module}' has no scraper/sources/{module}.py"},
    "cfg.bad_params": {"zh": "{where}的 {field} 缺少参数 {params}", "en": "{where}: {field} is missing parameter(s) {params}"},
    "type.string": {"zh": "文字", "en": "text"},
    "type.integer": {"zh": "整数", "en": "a whole number"},
    "type.number": {"zh": "数字", "en": "a number"},
    "type.boolean": {"zh": " true 或 false", "en": "true or false"},
    "type.object": {"zh": "一组键值（例如 {{adapter: filmbot}}）", "en": "a mapping (e.g. {{adapter: filmbot}})"},
    "type.array": {"zh": "列表", "en": "a list"},
    "type.null": {"zh": "空（null）", "en": "empty (null)"},
}


def current_lang(lang: str | None = None) -> str:
    """Explicit lang > CINEMA_LANG > LANG starting with zh > English."""
    lang = lang or os.environ.get("CINEMA_LANG") or ""
    if lang[:2] in ("zh", "en"):
        return lang[:2]
    return "zh" if os.environ.get("LANG", "").lower().startswith("zh") else "en"


def t(key: str, lang: str | None = None, **kw) -> str:
    entry = MESSAGES.get(key)
    if entry is None:
        return key
    return entry[current_lang(lang)].format(**kw)


def register(messages: dict[str, dict[str, str]]) -> None:
    """Other modules (the wizard, Issue comments) add their own keys here."""
    MESSAGES.update(messages)
