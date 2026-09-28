#!/bin/zsh
# Kept for the original macOS job (com.cinema.refresh) on the author's machine: update + publish.
# New setups don't need this file — use `python -m scraper.schedule on` (no publishing).
ROOT="${0:A:h:h}"
cd "$ROOT" || exit 1
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin"
exec "$ROOT/.venv/bin/python" -m scraper.update --publish
