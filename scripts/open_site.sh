#!/bin/zsh
# Opened by "Corridor Showtimes.app": show the page; if the data is stale (e.g. the Mac was off at
# update time), also start an update in the background — reload the page in a minute or two.
ROOT="${0:A:h:h}"
DATA="$ROOT/site/data.js"
if [[ ! -f "$DATA" || -n $(find "$DATA" -mmin +780 2>/dev/null) ]]; then
  launchctl kickstart "gui/$(id -u)/com.corridor-showtimes.update" >/dev/null 2>&1 \
    || launchctl kickstart "gui/$(id -u)/com.cinema.refresh" >/dev/null 2>&1 \
    || ( cd "$ROOT" && nohup "$ROOT/.venv/bin/python" -m scraper.update >/dev/null 2>&1 & )
fi
open "$ROOT/site/index.html"
