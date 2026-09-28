"""Add a cinema from its name and schedule URL (ARCHITECTURE §5.7).

    python -m scraper.add "Nitehawk Williamsburg" https://nitehawkcinema.com/williamsburg/ --region NYC
    python -m scraper.add "Vidiots" https://vidiotsfoundation.org/ --tz America/Los_Angeles --lang zh
    python -m scraper.add "…" https://… --json          # machine-readable result (scripts, CI)
    python -m scraper.add --verify nitehawk             # fetch once, save the fixture, run the contract

On success it appends the venue to config/venues.yaml, saves the pages it fetched as
tests/fixtures/<id>/ with a manifest, writes tests/test_<id>.py (a thin wrapper around the contract test)
and, in interactive mode, runs the scraper once so the site shows the new cinema. When it cannot finish
it writes handoff/<id>/BRIEF.md for any coding agent, or says plainly why the site cannot be read.
"""
from __future__ import annotations

import argparse
import copy
import json
import logging
import re
import sys
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from . import i18n
from .base import HttpClient, dedupe
from .config import read_raw
from .contract import MANIFEST, check, ext_for, load_fixture, summarize
from .i18n import t
from .models import RawPage, VenueConfig
from .normalize import now_utc_iso, today_local

ROOT = Path(__file__).resolve().parent.parent
VENUES_FILE = ROOT / "config" / "venues.yaml"
FIXTURES = ROOT / "tests" / "fixtures"
TESTS = ROOT / "tests"
PALETTE = ["#ff6b6b", "#4ecdc4", "#ffd166", "#06d6a0", "#118ab2", "#ef476f", "#8338ec", "#fb5607",
           "#3a0ca3", "#2ec4b6", "#e76f51", "#9b5de5", "#00bbf9", "#f15bb5", "#80b918", "#b5838d"]
REGION_BY_STATE = {"NY": "NYC", "PA": "PHL", "MA": "BOS", "IL": "CHI", "DC": "DC", "WA": "SEA", "OR": "PDX",
                   "MN": "MSP", "TX": "TX", "CA": "CA", "GA": "ATL", "MI": "DET", "CO": "DEN", "LA": "NOLA"}

i18n.register({
    "add.probing": {"zh": "正在查看 {url} …（最多 12 次请求，每次间隔 2 秒）", "en": "Looking at {url} … (at most 12 requests, 2 s apart)"},
    "add.found": {"zh": "识别到：{adapter}（{evidence}）", "en": "Recognised: {adapter} ({evidence})"},
    "add.trying": {"zh": "试抓 {n} 个候选数据源 …", "en": "Trying {n} candidate source(s) …"},
    "add.tz_guess": {"zh": "时区：{tz}（根据网页上的州 {state} 推断；不对请用 --tz 指定）",
                     "en": "Time zone: {tz} (from the state {state} on the page; override with --tz)"},
    "add.tz_default": {"zh": "没能从网页推断时区，按 America/New_York 处理；不对请用 --tz 重新添加",
                       "en": "Could not tell the time zone from the page; using America/New_York — re-run with --tz if wrong"},
    "add.tz_ask": {"zh": "这家影院在哪个时区？（例如 America/Los_Angeles，直接回车 = America/New_York）：",
                   "en": "Which time zone is the cinema in? (e.g. America/Los_Angeles; Enter = America/New_York): "},
    "add.ok": {"zh": "成功：{name} 通过「{adapter}」读取。{summary}", "en": "Done: {name} is read through '{adapter}'. {summary}"},
    "add.written": {"zh": "已写入：{files}", "en": "Wrote: {files}"},
    "add.open_site": {"zh": "打开 site/index.html 就能看到。", "en": "Open site/index.html to see it."},
    "add.auto_on": {"zh": "每天自动更新已开启，这家影院会一起更新。",
                    "en": "Daily automatic updates are on; this cinema will be included."},
    "add.auto_off": {"zh": "每天自动更新还没开启。开启：python -m scraper.schedule on",
                     "en": "Daily automatic updates are not on yet. Turn them on: python -m scraper.schedule on"},
    "add.exists": {"zh": "venues.yaml 里已经有 id「{id}」；换个名字或用 --id", "en": "venues.yaml already has id '{id}'; use another name or --id"},
    "why.recipe": {"zh": "网页上有场次时间，但它不是任何已知售票平台，需要为它写一份配方",
                   "en": "The page shows showtimes but is not on a known ticketing platform; it needs a recipe"},
    "why.browser_recipe": {"zh": "场次时间要等网页里的 JavaScript 运行后才出现，需要一份 render: browser 的配方",
                           "en": "Showtimes only appear after the page's JavaScript runs; it needs a recipe with render: browser"},
    "why.llm_failed": {"zh": "自动生成的配方三轮都没通过检查", "en": "Three rounds of automatic recipe generation did not pass the checks"},
    "why.agile_no_feed_guid": {"zh": "这家影院用 Agile Ticketing，但网页上找不到可用的 feed GUID；如果你能从影院拿到 Agile feed GUID，填进 source: {{adapter: agile, guid: …}} 效果最好",
                               "en": "The cinema sells through Agile Ticketing but no usable feed GUID is on its pages; an Agile feed GUID from the cinema, as source: {{adapter: agile, guid: …}}, works best"},
    "next.agent": {"zh": "把 handoff/{id}/BRIEF.md 交给任何 AI 编程助手（Claude Code、Cursor、ChatGPT），或在本仓库里用 Claude Code 运行 /add-venue \"{name}\" {url}",
                   "en": "Give handoff/{id}/BRIEF.md to any AI coding assistant (Claude Code, Cursor, ChatGPT), or run /add-venue \"{name}\" {url} with Claude Code in this repository"},
    "next.dry_run": {"zh": "（--dry-run：什么都没写。去掉 --dry-run 重新运行，会生成 handoff/{id}/BRIEF.md 任务书）",
                     "en": "(--dry-run: nothing was written. Run again without --dry-run to get the brief in handoff/{id}/BRIEF.md)"},
    "next.key": {"zh": "或者设置 ANTHROPIC_API_KEY 后重新运行，让 Claude 自动写配方", "en": "Or set ANTHROPIC_API_KEY and run again so Claude writes the recipe"},
    "blocked": {"zh": "{name} 的网站挡住了程序访问（{what}）。本项目不绕过防火墙或验证码，所以这家没法自动抓取。",
                "en": "{name}'s website blocks automated access ({what}). This project does not work around firewalls or CAPTCHAs, so it cannot be read automatically."},
    "blocked.fallback": {"zh": "纽约 / 旧金山的影院如果被 screenslate.com 收录，可以只配 fallback: {{adapter: screenslate, nid: …}} 作为唯一数据源（见 SOURCES.md §10）。",
                         "en": "For New York / San Francisco cinemas listed on screenslate.com, a fallback: {{adapter: screenslate, nid: …}} alone can be the source (SOURCES.md §10)."},
    "no_times": {"zh": "在 {url} 上没有找到任何场次时间。多半是给的首页而排片在别的页面（例如 /calendar、/showtimes），换成排片页的链接再试。",
                 "en": "No showtimes found at {url}. Usually that means the schedule lives on another page (/calendar, /showtimes …) — try again with the schedule page's link."},
    "unreachable": {"zh": "打不开 {url}（{what}）。检查一下网址。", "en": "Could not open {url} ({what}). Check the address."},
    "verify.saved": {"zh": "已保存 fixture：{path}", "en": "Saved fixture: {path}"},
    "verify.not_saved": {"zh": "tests/fixtures/{id}/ 是手工维护的，本次只检查、不覆盖", "en": "tests/fixtures/{id}/ is hand-maintained; checked but not overwritten"},
    "verify.pass": {"zh": "契约检查通过。", "en": "Contract checks pass."},
    "verify.fail": {"zh": "契约检查有 {n} 处问题：", "en": "Contract checks found {n} problem(s):"},
    "verify.fetch_failed": {"zh": "抓取失败：{error}", "en": "Fetch failed: {error}"},
})


# ------------------------------------------------------------------ small helpers
def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"['’]", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    s = re.sub(r"^the-", "", s)
    return s[:40].strip("-") or "venue"


def existing_venues(path: Path) -> list[dict]:
    return read_raw(path)[1] if path.exists() else []


def unique_id(base: str, taken: set[str]) -> str:
    vid, n = base, 2
    while vid in taken:
        vid, n = f"{base}-{n}", n + 1
    return vid


def pick_color(used: set[str]) -> str:
    return next((c for c in PALETTE if c.lower() not in used), PALETTE[len(used) % len(PALETTE)])


def short_name(name: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z0-9]+", name) if w.lower() not in ("the", "of", "and", "cinema", "theater", "theatre")]
    return ("".join(w[0] for w in words[:4]).upper() if len(words) > 1 else (words[0][:4] if words else "?")) or "?"


def append_venue(entry: dict, path: Path = VENUES_FILE) -> None:
    """Append one venue to venues.yaml, keeping the file's comments and existing entries byte-for-byte."""
    version, _ = read_raw(path) if path.exists() else (2, [])
    text = path.read_text(encoding="utf-8") if path.exists() else "version: 2\nvenues:\n"
    body = yaml.safe_dump([entry], sort_keys=False, allow_unicode=True, width=120, default_flow_style=None)
    indent = "  " if version == 2 else ""
    block = "\n".join(indent + line if line else line for line in body.rstrip().split("\n"))
    path.write_text(text.rstrip("\n") + "\n\n" + block + "\n", encoding="utf-8")


def write_fixture(venue_id: str, pages: list[RawPage], root: Path = FIXTURES) -> Path:
    d = root / venue_id
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("page_*"):
        old.unlink()
    items = []
    for i, p in enumerate(pages):
        name = f"page_{i}.{ {'json': 'json', 'ics': 'ics'}.get(p.ext, 'html') }"
        (d / name).write_text(p.body, encoding="utf-8")
        items.append({"file": name, "url": p.url})
    fetched = min((p.fetched_at for p in pages), default=now_utc_iso())
    manifest = {"generated_by": "scraper.add", "fetched_at": fetched, "pages": items}
    (d / MANIFEST).write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return d


def write_test(venue_id: str, name: str, root: Path = TESTS) -> Path:
    path = root / f"test_{venue_id.replace('-', '_')}.py"
    path.write_text(f'''"""{name}: contract test on tests/fixtures/{venue_id}/ (written by python -m scraper.add)."""
from scraper.contract import check_venue


def test_{venue_id.replace('-', '_')}_contract():
    problems = check_venue("{venue_id}")
    assert not problems, "\\n".join(problems)
''', encoding="utf-8")
    return path


def is_generated_fixture(venue_id: str, root: Path = FIXTURES) -> bool:
    m = root / venue_id / MANIFEST
    if not m.exists():
        return not (root / venue_id).exists()
    return (yaml.safe_load(m.read_text(encoding="utf-8")) or {}).get("generated_by") == "scraper.add"


def sample_lines(rows, n: int = 10) -> list[str]:
    out = []
    for s in sorted(rows, key=lambda s: s.start)[:n]:
        st = datetime.fromisoformat(s.start)
        meta = ", ".join(str(x) for x in (s.director, s.year, s.format) if x)
        out.append(f"{st:%a %m/%d} {st.strftime('%I:%M%p').lstrip('0').lower()}  {s.title}" + (f" ({meta})" if meta else ""))
    return out


# ------------------------------------------------------------------ add
def build_entry(vid: str, name: str, url: str, region: str, tz: str, color: str, source: dict) -> dict:
    return {"id": vid, "name": name, "short": short_name(name), "region": region, "timezone": tz,
            "color": color, "website": url, "source": source, "fallback": None,
            "horizon_days": 45, "rate_limit_s": 2}


def add(name: str, url: str, *, region: str | None = None, tz: str | None = None, venue_id: str | None = None,
        lang: str | None = None, json_mode: bool = False, run_after: bool = True, dry_run: bool = False,
        venues_file: Path = VENUES_FILE, fixtures: Path = FIXTURES, tests_dir: Path = TESTS,
        handoff_root: Path | None = None, probe=None, client=None, use_llm: bool | None = None,
        llm_client=None, render=None, today: date | None = None, ask=input, say=print) -> dict:
    from .detect import detect_site, render_with_browser
    from .handoff import write_handoff

    url = url if "://" in url else f"https://{url}"
    existing = existing_venues(venues_file)
    taken = {v.get("id") for v in existing if isinstance(v, dict)}
    vid = venue_id or unique_id(slugify(name), taken)
    if venue_id and venue_id in taken:
        return {"status": "error", "message": t("add.exists", lang, id=venue_id)}
    progress = (lambda *_: None) if json_mode else say
    progress(t("add.probing", lang, url=url))

    venue = VenueConfig(id=vid, name=name, timezone=tz or "America/New_York", region=region or "",
                        source={"adapter": "custom", "module": vid}, horizon_days=45, rate_limit_s=2)
    d = detect_site(url, venue, probe=probe, client=client, use_llm=use_llm, llm_client=llm_client,
                    render=render if render is not None else render_with_browser, today=today)

    # time zone: flag > page > question > default (only worth asking when the venue can be added)
    if not tz and d.status not in ("ok", "needs_agent"):
        tz = d.timezone or "America/New_York"
    if not tz:
        if d.timezone:
            tz = d.timezone
            progress(t("add.tz_guess", lang, tz=tz, state=d.state))
        elif not json_mode and sys.stdin.isatty():
            tz = (ask(t("add.tz_ask", lang)) or "").strip() or "America/New_York"
        else:
            tz = "America/New_York"
            progress(t("add.tz_default", lang))
    if tz != venue.timezone and d.status == "ok" and d.best:
        from .detect import trial
        venue.timezone = tz
        if d.best.candidate.adapter != "recipe":
            d.best = trial(d.best.candidate, venue, client=client, today=today)
    region = region or REGION_BY_STATE.get(d.state or "") or d.state or "US"
    color = pick_color({str(v.get("color", "")).lower() for v in existing if isinstance(v, dict)})

    result: dict = {"status": d.status, "reason": d.reason, "venue_id": vid, "name": name, "url": url,
                    "timezone": tz, "region": region, "evidence": [e for c in d.candidates for e in c.evidence],
                    "hints": d.probe.hints, "files": [], "next_steps": []}
    for c in d.candidates:
        progress(t("add.found", lang, adapter=c.adapter, evidence="; ".join(c.evidence)))

    if d.status == "ok":
        source = d.best.candidate.source
        entry = build_entry(vid, name, url, region, tz, color, source)
        if d.needs_browser:
            entry["max_requests_per_run"] = 10
        rows = d.best.screenings
        summary = summarize(rows, lang=i18n.current_lang(lang))
        result.update(adapter=source["adapter"], source=source, entry=entry, count=len(rows),
                      summary=summary, sample=sample_lines(rows),
                      message=t("add.ok", lang, name=name, adapter=source["adapter"], summary=summary))
        if not dry_run:
            if d.recipe is not None:
                from .recipe_gen import save_recipe
                saved = save_recipe(vid, d.recipe, header=f"# {name} — written by Claude via python -m scraper.add; checked on {url}")
                result["files"].append(_rel(saved))
            append_venue(entry, venues_file)
            fx = write_fixture(vid, d.best.pages, fixtures)
            test = write_test(vid, name, tests_dir)
            result["files"] += [_rel(venues_file), _rel(fx), _rel(test)]
        say_lines = [result["message"], *("  " + s for s in result["sample"])]
        if result["files"]:
            say_lines.append(t("add.written", lang, files=", ".join(result["files"])))
        for line in say_lines:
            progress(line)
        if not dry_run:
            from .schedule import is_on
            result["auto_update"] = is_on()
        if run_after and not dry_run and not json_mode:
            from .run import main as run_main
            run_main(["--venue", vid])
            progress(t("add.open_site", lang))
            progress(t("add.auto_on" if result["auto_update"] else "add.auto_off", lang))
        return result

    if d.status == "needs_agent":
        why_key = "agile_no_feed_guid" if "agile_no_feed_guid" in d.probe.hints and d.reason == "recipe" else d.reason
        why = t(f"why.{why_key}", lang)
        entry = build_entry(vid, name, url, region, tz, color, {"adapter": "recipe", "recipe": vid})
        result.update(message=why, entry=entry)
        result["next_steps"].append(t("next.dry_run" if dry_run else "next.agent", lang, id=vid, name=name, url=url))
        from .recipe_gen import available
        if not available():
            result["next_steps"].append(t("next.key", lang))
        if not dry_run:
            out = write_handoff(entry, url, d, why, root=handoff_root)
            result["handoff"] = _rel(out)
            result["brief"] = (out / "BRIEF.md").read_text(encoding="utf-8")
        for line in [why, *result["next_steps"]]:
            progress(line)
        return result

    if d.status == "blocked":
        result["message"] = t("blocked", lang, name=name, what=d.reason)
        result["next_steps"].append(t("blocked.fallback", lang))
    elif d.reason == "unreachable":
        main = next(iter(d.probe.responses.values()), None)
        what = (main.error or f"HTTP {main.status}") if main else "no response"
        result["message"] = t("unreachable", lang, url=url, what=what)
    else:
        result["message"] = t("no_times", lang, url=url)
    for line in [result["message"], *result["next_steps"]]:
        progress(line)
    return result


def _rel(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(ROOT))
    except ValueError:
        return str(p)


# ------------------------------------------------------------------ verify
def verify(venue_id: str, *, lang: str | None = None, client=None, fixtures: Path = FIXTURES, say=print) -> dict:
    """Fetch once, save the fixture (only for wizard-made fixtures), run the contract, report."""
    from .registry import build_scraper, load_venues
    venue = {v.id: v for v in load_venues()}[venue_id]
    scraper = build_scraper(venue, client=client)
    try:
        pages = scraper.fetch()
    except Exception as e:  # noqa: BLE001
        msg = t("verify.fetch_failed", lang, error=f"{type(e).__name__}: {e}")
        say(msg)
        return {"status": "failed", "venue_id": venue_id, "message": msg}
    finally:
        scraper.close()
    if is_generated_fixture(venue_id, fixtures):
        path = write_fixture(venue_id, pages, fixtures)
        say(t("verify.saved", lang, path=_rel(path)))
        fx = load_fixture(path)
        pages, fetched = fx.pages, fx.fetched_date
    else:
        say(t("verify.not_saved", lang, id=venue_id))
        fetched = today_local(venue.timezone)
    rows = dedupe(build_scraper(venue, client=object()).parse(pages))
    problems = check(venue, rows, fetched, dedupe(build_scraper(venue, client=object()).parse(pages)))
    summary = summarize(rows, lang=i18n.current_lang(lang))
    say(summary)
    if problems:
        say(t("verify.fail", lang, n=len(problems)))
        for p in problems:
            say("  - " + p)
    else:
        say(t("verify.pass", lang))
    return {"status": "ok" if not problems else "failed", "venue_id": venue_id, "count": len(rows),
            "summary": summary, "problems": problems}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m scraper.add", description="Add a cinema from its name and schedule URL.",
                                 epilog="Example: python -m scraper.add \"Nitehawk Williamsburg\" https://nitehawkcinema.com/williamsburg/")
    ap.add_argument("name", nargs="?", help="cinema name, e.g. \"Roxy Cinema\"")
    ap.add_argument("url", nargs="?", help="the page that lists showtimes")
    ap.add_argument("--region", help="region label for the site's filter (NYC, PHL, LA …); default from the address")
    ap.add_argument("--tz", help="IANA time zone, e.g. America/Los_Angeles; default from the address")
    ap.add_argument("--id", dest="venue_id", help="venue id (default: from the name)")
    ap.add_argument("--lang", choices=["zh", "en"], help="message language (default: CINEMA_LANG / LANG)")
    ap.add_argument("--json", action="store_true", help="print one JSON object (for scripts and CI)")
    ap.add_argument("--verify", metavar="ID", help="fetch an existing venue once, save its fixture and run the contract")
    ap.add_argument("--no-run", action="store_true", help="don't run the scraper after adding")
    ap.add_argument("--dry-run", action="store_true", help="detect only; write nothing")
    ap.add_argument("--no-llm", action="store_true", help="never call Claude, even with an API key")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING if not args.json else logging.ERROR, format="%(levelname)s %(message)s")
    quiet = (lambda *_: None) if args.json else print

    if args.verify:
        client = HttpClient()
        try:
            res = verify(args.verify, lang=args.lang, client=client, say=quiet)
        finally:
            client.close()
    else:
        if not args.name or not args.url:
            ap.error("give a cinema name and its schedule URL, or --verify <id>")
        client = HttpClient()
        try:
            res = add(args.name, args.url, region=args.region, tz=args.tz, venue_id=args.venue_id, lang=args.lang,
                      json_mode=args.json, run_after=not args.no_run, dry_run=args.dry_run, client=client,
                      use_llm=False if args.no_llm else None)
        finally:
            client.close()
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    return 1 if res.get("status") in ("error", "failed") else 0


if __name__ == "__main__":
    sys.exit(main())
