"""Give the published page's own files a content version: index.html's `app.js` becomes `app.js?v=<hash>`.

GitHub Pages lets browsers cache every file for 10 minutes. With the version in the address, a plain
reload of the page (which re-checks index.html) always loads the scripts and styles that belong to it,
never a stale app.js beside a fresh data.js. Run on the folder about to be published:

    python scripts/stamp_assets.py <site folder>

Pages in sub-folders (the phone layout, m/venues/index.html) get the same treatment for every local script and
stylesheet they load ("../_shared/core.js", "../../data.js"): a new phone page must never run with a cached old
shared script.

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


LOCAL = re.compile(r'((?:src|href)=")((?![a-z]+:|/)[^"?#]+\.(?:js|css))(?:\?v=[^"]*)?"')


def stamp_page(page: Path) -> None:
    """Version every local .js / .css a nested page loads, resolved against the page's own folder."""
    def one(m: re.Match) -> str:
        target = (page.parent / m.group(2)).resolve()
        return f'{m.group(1)}{m.group(2)}?v={version(target.read_bytes())}"' if target.is_file() else m.group(0)
    page.write_text(LOCAL.sub(one, page.read_text(encoding="utf-8")), encoding="utf-8")


def stamp_folder(folder: Path) -> dict[str, str]:
    versions = {n: version((folder / n).read_bytes()) for n in ASSETS if (folder / n).exists()}
    index = folder / "index.html"
    index.write_text(stamp(index.read_text(encoding="utf-8"), versions), encoding="utf-8")
    for page in sorted(folder.glob("*/**/index.html")):
        stamp_page(page)
    return versions


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python scripts/stamp_assets.py <site folder>")
    for name, v in stamp_folder(Path(sys.argv[1])).items():
        print(f"stamp: {name}?v={v}")
