"""Turn the Philadelphia Film Festival's printed schedule grid (PDF) into config/schedules/<name>.yaml.

    /opt/anaconda3/bin/python3 scripts/import_pff_grid.py ~/Downloads/PFF35-Schedule-Grid.pdf pff35

Needs PyMuPDF (`pip install pymupdf`; not a dependency of the scraper). Used when the festival's screenings
are missing from the Philadelphia Film Society's Agile feed (SOURCES.md §9); scraper/sources/filmadelphia.py
reads the YAML and drops any row the feed itself lists.

The grid: one band per day ("THURSDAY 10.15", rotated, left of its rows), one row per theatre
("FILM SOCIETY / BOURSE 1"), one cell per screening ("7:15 • WHEN A WITNESS RECANTS (117 min, p. 99)"),
coloured by section (the KEY). Times carry no am/pm: along a row they only move forward, so the first one is
morning from 9 to 11 and afternoon otherwise, and each later one is the first reading after the previous start
(10:30 after 7:30 is 10:30pm, 12:00 after 8:30pm is midnight). EVENTS and PANELS rows are not screenings.
"""
from __future__ import annotations

import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pymupdf
import yaml

ROOT = Path(__file__).resolve().parents[1]
YEAR = 2026
DAY = re.compile(r"^(MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY)\s+(\d{1,2})\.(\d{1,2})$")
CELL = re.compile(r"^(\d{1,2}):(\d{2})\s*•\s*(.+?)\s*\((\d+)\s*min,\s*p\.\s*(\d+)\)\s*$", re.I | re.S)
SECTIONS = ["After Hours", "Centerpieces", "Cinema de France", "Community Screenings", "Filmadelphia",
            "From the Vaults", "Made in USA", "Masters of Cinema", "Non/Fiction", "Sight & Soundtrack",
            "Spotlights", "State of the Union", "This Animated Life", "World View"]     # the KEY, as the festival spells them
KEY_NAMES = {name.upper(): name for name in SECTIONS}


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def key_colours(page) -> dict[tuple, str]:
    """KEY swatches: the small filled square just left of each section name."""
    labels = [(b[:4], flat(b[4])) for b in page.get_text("blocks") if flat(b[4]) in KEY_NAMES]
    swatches = [d for d in page.get_drawings() if d.get("fill") and d["rect"].width < 15 and d["rect"].height < 15]
    out = {}
    for (x0, y0, x1, y1), name in labels:
        near = [d for d in swatches if 0 < x0 - d["rect"].x1 < 8 and abs((d["rect"].y0 + d["rect"].y1) / 2 - (y0 + y1) / 2) < 4]
        if near:
            out[tuple(near[0]["fill"])] = KEY_NAMES[name]
    return out


def section_of(page, rect, keys: dict[tuple, str]) -> str | None:
    """The section whose key colour is closest to the fill behind the cell (white = none)."""
    point = pymupdf.Point((rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2)
    # one shape may hold several separate cell rectangles; the last one painted under the point is the one seen
    hits = [d["fill"] for d in page.get_drawings() if d.get("fill")
            and any(it[0] == "re" and it[1].contains(point) and it[1].width > 30 for it in d["items"])]
    if not hits:
        return None
    fill = hits[-1]
    if min(fill) > 0.97:
        return None
    colour, name = min(((c, n) for c, n in keys.items()), key=lambda cn: sum((a - b) ** 2 for a, b in zip(cn[0], fill)))
    return name if sum((a - b) ** 2 for a, b in zip(colour, fill)) < 0.03 else None


def read(pdf: Path) -> list[dict]:
    doc = pymupdf.open(pdf)
    keys = {}
    for page in doc:
        keys.update(key_colours(page))
    rows = []
    for page in doc:
        blocks = [(b[:4], b[4]) for b in page.get_text("blocks")]
        half = page.rect.width / 2 if page.rect.width > 1000 else page.rect.width   # a two-page spread
        side = lambda r: int(r[0] >= half)                                            # noqa: E731
        days = [(r, date(YEAR, int(m.group(2)), int(m.group(3)))) for r, t in blocks if (m := DAY.match(flat(t)))]
        labels = [(r, flat(t)) for r, t in blocks if flat(t).startswith(("FILM SOCIETY", "EVENTS", "PANELS"))]
        cells = [(r, m) for r, t in blocks if (m := CELL.match(flat(t)))]
        # rows of one day sit close together; days are separated by a wider gap. Each group of rows takes the
        # day label nearest its middle.
        day_of_row: dict[tuple, date] = {}
        for sd in (0, 1):
            ys = sorted({round(lr[0][1]) for lr in labels if side(lr[0]) == sd})
            groups, cur = [], []
            for y in ys:
                if cur and y - cur[-1] > 31:
                    groups.append(cur)
                    cur = []
                cur.append(y)
            groups += [cur] if cur else []
            for g in groups:
                mid = (g[0] + g[-1]) / 2
                near = [(abs((dr[1] + dr[3]) / 2 - mid), d) for dr, d in days if side(dr) == sd]
                if near:
                    for y in g:
                        day_of_row[(sd, y)] = min(near)[1]
        by_row: dict[tuple, list] = {}
        for r, m in cells:
            label = min((lr for lr in labels if side(lr[0]) == side(r) and lr[0][2] < r[0]),
                        key=lambda lr: abs(lr[0][1] - r[1]), default=None)
            if label is None or abs(label[0][1] - r[1]) > 5 or not label[1].startswith("FILM SOCIETY"):
                continue
            day = day_of_row.get((side(label[0]), round(label[0][1])))
            if day is None:
                raise SystemExit(f"no day for cell {flat(m.group(0))!r} at {r}")
            by_row.setdefault((day, label[1], round(label[0][1])), []).append((r, m))
        for (day, screen, _), items in by_row.items():
            prev = None
            for r, m in sorted(items, key=lambda it: it[0][0]):
                hour, minute = int(m.group(1)), int(m.group(2))
                if prev is None:
                    t = datetime(day.year, day.month, day.day, hour if 9 <= hour <= 11 else hour % 12 + 12, minute)
                else:
                    t = datetime(day.year, day.month, day.day, hour % 12, minute)
                    while t <= prev:
                        t += timedelta(hours=12)
                prev = t
                rows.append({"start": t.strftime("%Y-%m-%dT%H:%M"), "screen": screen.title(),
                             "title": flat(m.group(3)), "runtime_min": int(m.group(4)), "page": int(m.group(5)),
                             "section": section_of(page, r, keys)})
    # the grid cuts long titles ("LABRADOR — AUTOPSY OF..."); another cell often has them whole
    for r in rows:
        r["title"] = re.sub(r"\s*—\s*", " — ", r["title"])
    whole = {r["title"] for r in rows if not r["title"].endswith("...")}
    for r in rows:
        if r["title"].endswith("..."):
            stem = r["title"][:-3].rstrip()
            r["title"] = next((w for w in sorted(whole) if w.startswith(stem)), stem + "…")
    return sorted(rows, key=lambda x: (x["start"], x["screen"]))


def main() -> None:
    pdf, name = Path(sys.argv[1]).expanduser(), sys.argv[2]
    rows = read(pdf)
    out = ROOT / "config" / "schedules" / f"{name}.yaml"
    out.parent.mkdir(exist_ok=True)
    head = (f"# {name.upper()} screenings, read from the festival's printed schedule grid ({pdf.name}) by\n"
            f"# scripts/import_pff_grid.py. Used by scraper/sources/filmadelphia.py only for screenings the PFS feed\n"
            f"# doesn't list. Times are local (America/New_York); runtime is the programme's total.\n")
    out.write_text(head + yaml.safe_dump({"series": "Philadelphia Film Festival", "screenings": rows},
                                         sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")
    print(f"{len(rows)} screenings -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
