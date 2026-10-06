#!/bin/zsh
# Publish site/ (page + freshly exported data.js) to the gh-pages branch, which GitHub Pages serves.
# Each publish is a single orphan commit force-pushed over the previous one, so twice-daily data
# updates never grow the repository. Called by refresh.sh; safe to run by hand.
set -euo pipefail
ROOT="${0:A:h:h}"
cd "$ROOT"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

if ! git remote get-url origin >/dev/null 2>&1; then
  echo "publish: no 'origin' remote — skipping"; exit 0
fi
[[ -f site/data.js ]] || { echo "publish: site/data.js missing — run the scraper first"; exit 1; }

STAGE=$(mktemp -d)
INDEX=$(mktemp)
trap 'rm -rf "$STAGE" "$INDEX"' EXIT
cp site/index.html site/app.js site/calendar.js site/styles.css site/data.js site/manifest.webmanifest site/*.png "$STAGE"/
touch "$STAGE/.nojekyll"                      # serve files as-is, no Jekyll processing

rm -f "$INDEX"
tree=$(GIT_INDEX_FILE="$INDEX" git --work-tree="$STAGE" add -A . && GIT_INDEX_FILE="$INDEX" git write-tree)
commit=$(git commit-tree "$tree" -m "Publish showtimes $(date -u +%Y-%m-%dT%H:%MZ)")
git push --quiet --force origin "${commit}:refs/heads/gh-pages"
echo "publish: pushed $(git rev-parse --short "$commit") to gh-pages"
