#!/bin/zsh
# Opened by "Corridor Showtimes.app": show the page; if the data is stale (e.g. the Mac was off at
# 01:00 and 13:00), also kick the launchd refresh in the background — reload the page in ~1 min.
ROOT="${0:A:h:h}"
DATA="$ROOT/site/data.js"
if [[ ! -f "$DATA" || -n $(find "$DATA" -mmin +780 2>/dev/null) ]]; then
  launchctl kickstart "gui/$(id -u)/com.cinema.refresh" >/dev/null 2>&1 || true
fi
open "$ROOT/site/index.html"
