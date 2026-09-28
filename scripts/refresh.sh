#!/bin/zsh
# Scrape all venues, export site/data.js, prune old raw snapshots.
# Run by launchd at 01:00 and 13:00 (scripts/com.cinema.refresh.plist); safe to run by hand.
set -uo pipefail

ROOT="${0:A:h:h}"
cd "$ROOT" || exit 1
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin"
export PYTHONUNBUFFERED=1
PY="$ROOT/.venv/bin/python"
LOG="$ROOT/logs/refresh.log"
LOCK="$ROOT/data/.refresh.lock"
mkdir -p "$ROOT/logs" "$ROOT/data"

# keep the log under ~5 MB (last 20k lines)
if [[ -f "$LOG" && $(stat -f%z "$LOG") -gt 5000000 ]]; then
  tail -n 20000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

log() { print -r -- "$(date '+%Y-%m-%d %H:%M:%S') [refresh] $*" >> "$LOG"; }

# one run at a time (a MoMA browser attempt can take a minute)
if ! mkdir "$LOCK" 2>/dev/null; then
  if [[ -n $(find "$LOCK" -maxdepth 0 -mmin +60 2>/dev/null) ]]; then
    log "removing stale lock"; rm -rf "$LOCK"; mkdir "$LOCK"
  else
    log "another refresh is running — skipping"; exit 0
  fi
fi
trap 'rm -rf "$LOCK"' EXIT

log "start"
"$PY" -m scraper.run >> "$LOG" 2>&1
rc=$?
# optional: let Claude repair recipes that stopped working (needs ANTHROPIC_API_KEY; once per venue per day)
if [[ "${AUTO_REPAIR:-0}" == "1" ]]; then
  "$PY" -m scraper.repair --failed >> "$LOG" 2>&1 || log "recipe repair did not fix everything (see above)"
fi
"$PY" -m scraper.export >> "$LOG" 2>&1 || rc=$?
find "$ROOT/data/raw" -mindepth 1 -maxdepth 1 -type d -mtime +14 -exec rm -rf {} + 2>/dev/null

# publish to GitHub Pages (only if this checkout has an 'origin' remote); never fails the refresh
if [[ $rc -eq 0 ]]; then
  "$ROOT/scripts/publish.sh" >> "$LOG" 2>&1 || log "publish failed (see above) — site not updated online"
fi
log "done (exit $rc)"
exit $rc
