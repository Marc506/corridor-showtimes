"""One scheduled update, on any OS: scrape → export → prune old raw snapshots → (optionally) publish.

    python -m scraper.update              # what `python -m scraper.schedule on` runs twice a day
    python -m scraper.update --publish    # also push site/ to GitHub Pages (the author's machine only)

Everything goes to logs/refresh.log. It never publishes unless --publish is given, so anyone who
downloads the project can schedule it safely. `scraper.run` holds the run lock, so a manual run and
a scheduled one never overlap.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "logs" / "refresh.log"
RAW = ROOT / "data" / "raw"
LOG_MAX_BYTES = 5_000_000
LOG_KEEP_LINES = 20_000
RAW_KEEP_DAYS = 14


def rotate_log(path: Path = LOG, max_bytes: int = LOG_MAX_BYTES, keep_lines: int = LOG_KEEP_LINES) -> None:
    """Keep the log small: past max_bytes, keep only the last keep_lines lines."""
    if path.exists() and path.stat().st_size > max_bytes:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        path.write_text("".join(lines[-keep_lines:]), encoding="utf-8")


def prune_raw(raw: Path = RAW, keep_days: int = RAW_KEEP_DAYS, now: float | None = None) -> list[str]:
    """Delete data/raw/<date>/ folders older than keep_days; returns what was removed."""
    if not raw.is_dir():
        return []
    cutoff = (now or time.time()) - keep_days * 86400
    removed = []
    for d in raw.iterdir():
        if d.is_dir() and d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)
            removed.append(d.name)
    return removed


def _log(fh, msg: str) -> None:
    fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} [update] {msg}\n")
    fh.flush()


def _step(fh, *args: str) -> int:
    """Run `python -m <args>` in the project folder, output appended to the log."""
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    return subprocess.run([sys.executable, "-m", *args], cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT,
                          env=env).returncode


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m scraper.update", description=__doc__.split("\n\n")[0])
    ap.add_argument("--publish", action="store_true", help="also publish site/ to GitHub Pages (scripts/publish.sh)")
    ap.add_argument("--repair", action="store_true",
                    help="let the optional recipe repair fix failing recipes (needs an Anthropic API key); "
                         "same as AUTO_REPAIR=1")
    args = ap.parse_args(argv)

    LOG.parent.mkdir(parents=True, exist_ok=True)
    rotate_log()
    with open(LOG, "a", encoding="utf-8") as fh:
        _log(fh, f"start ({ROOT})")
        rc = _step(fh, "scraper.run", "--no-export")
        if args.repair or os.environ.get("AUTO_REPAIR") == "1":
            if _step(fh, "scraper.repair", "--failed") != 0:
                _log(fh, "recipe repair did not fix everything (see above)")
        export_rc = _step(fh, "scraper.export")
        rc = rc or export_rc
        removed = prune_raw()
        if removed:
            _log(fh, f"pruned {len(removed)} old raw snapshot folder(s)")
        if args.publish:
            publish = ROOT / "scripts" / "publish.sh"
            if rc != 0:
                _log(fh, "not publishing: the update had errors")
            elif os.name == "nt" or not publish.exists():
                _log(fh, "not publishing: scripts/publish.sh needs macOS/Linux")
            elif subprocess.run([str(publish)], cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT).returncode != 0:
                _log(fh, "publish failed (see above) — site not updated online")
        _log(fh, f"done (exit {rc})")
    return rc


if __name__ == "__main__":
    sys.exit(main())
