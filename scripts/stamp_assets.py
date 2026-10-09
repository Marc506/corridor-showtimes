"""Give the published page's own files a content version: index.html's `app.js` becomes `app.js?v=<hash>`.

GitHub Pages lets browsers cache every file for 10 minutes. With the version in the address, a plain
reload of the page (which re-checks index.html) always loads the scripts and styles that belong to it,
never a stale app.js beside a fresh data.js. Run on the folder about to be published:

    python scripts/stamp_assets.py <site folder>

The working copy in site/ is left alone, so opening site/index.html locally is unchanged.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ASSETS = ("styles.css", "data.js", "calendar.js", "app.js", "plan.js", "planner.js", "planner.css")


def version(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:10]


def stamp(html: str, versions: dict[str, str]) -> str:
    """Rewrite src="name" / href="name" (with or without an old ?v=) to name?v=<version>."""
    for name, v in versions.items():
        html = re.sub(rf'((?:src|href)="){re.escape(name)}(?:\?v=[^"]*)?"', rf'\g<1>{name}?v={v}"', html)
    return html


def stamp_folder(folder: Path) -> dict[str, str]:
    versions = {n: version((folder / n).read_bytes()) for n in ASSETS if (folder / n).exists()}
    index = folder / "index.html"
    index.write_text(stamp(index.read_text(encoding="utf-8"), versions), encoding="utf-8")
    return versions


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python scripts/stamp_assets.py <site folder>")
    for name, v in stamp_folder(Path(sys.argv[1])).items():
        print(f"stamp: {name}?v={v}")
