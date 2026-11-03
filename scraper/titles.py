"""Titles: what a cinema writes around a film's name, moved to where it belongs.

Every source's screenings pass through `tidy()` once, after the source has parsed and enriched them
(BaseScraper.run), so a rule found at one cinema protects all of them. Each rule comes from a real listing;
tests/fixtures/titles.yaml keeps every one of them, and the things that must stay, as a regression table.

    run label       "FJORD (First Run)" (PFS)                            -> "Fjord"
    the building    "NAZA (PFS EAST)" (PFS)                              -> "Naza"
    print format    "WERWULF (35MM)", "Suspiria [4K DCP]"                -> format 35mm / note "4K DCP"
    event note      "(Lloyd Kaufman in person!)", "(Encore)"             -> note
    series prefix   "Playback: City of God" (series "Playback: …"), "EC: The General" (Anthology, many),
                    "The Metropolitan Opera: Carmen" (Kendall)            -> title after the colon, series kept / set
    presenter       "ACE Presents: Ghost World", "ArteEast Presents Sunshine Express"
                                                                          -> title, note "ACE presents"
    event prefix    "Members Only Preview: All of a Sudden"              -> title, note "Members Only Preview"
    support short   "Two Seasons, Two Strangers preceded by Nagahama"    -> title, note "Preceded by Nagahama"
    anniversary     "Ghost in the Shell: 30th Anniversary Remaster"      -> title, note
    year            "The Devils (1971)" (Coolidge)                       -> "The Devils", year 1971
    director's      "Ken Russell’s The Devils" by Ken Russell (BAM)      -> "The Devils"

What stays: a film's own subtitle ("Blade Runner: The Final Cut", "Bob Dylan: Dont Look Back"), parts
("My Undesirable Friends: Part II", "Kill Bill: Vol. 1"), a franchise ("Star Wars: Episode IV …"), alternative
titles ("The Rites of May (aka Itim)"), possessives that aren't the director ("Schindler's List").

`python -m scraper.titles` lists the upcoming titles that still look like they carry a label (every update logs
it). Each one either becomes a rule here plus a row in the table, or, when it is the film's own name, a line in
config/titles_reviewed.txt so it isn't listed again.
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

from .models import Screening, VenueConfig
from .normalize import clean_text, drop_director_possessive, smart_title, tidy_title, title_norm

# a prefix that names a part, not a series: "My Undesirable Friends: Part II", "Kill Bill: Vol. 1", "Dune: Part Two"
PART = re.compile(r"^(?:part|pt\.?|vol(?:ume)?\.?|chapter|episode|ep\.?|no\.?|pgm|program(?:me)?|book|season)\b", re.I)
SERIES_ALIASES = {"EC": "Essential Cinema"}             # Anthology's Essential Cinema Repertory
PRESENTER = re.compile(r"^(?P<who>[^:]{2,60}?)\s+(?:co-)?presents?:?\s+(?P<rest>\S.*)$", re.I)
EVENT_PREFIX = re.compile(r"^(?P<what>(?:members?[- ]only\s+)?(?:sneak\s+)?preview|relaxed screenings?|"
                          r"sensory[- ]friendly(?: screening)?|opening night|closing night|centerpiece)\s*:\s+(?P<rest>\S.*)$",
                          re.I)
SUPPORT = re.compile(r"^(?P<main>.+?)\s+(?P<how>preceded|followed)\s+by\s+(?P<short>\S.*)$", re.I)
ANNIVERSARY = re.compile(r"\s*[:–—-]?\s+(?P<what>\d+(?:st|nd|rd|th)\s+anniversary(?:\s+[\w-]+){0,3})\s*$", re.I)
YEAR = re.compile(r"\s*\(((?:18|19|20)\d{2})\)\s*$")
RESTORATION = re.compile(r"\s*\((?P<what>(?:new\s+)?(?:\d+k\s+)?restor(?:ation|ed)(?:\s+[\w-]+){0,2})\)\s*$", re.I)
# a trailing run of capitals in a title that isn't capitals: "Caligari's Cure LIGHTBOX MEMBERS SCREENING"
CAPS_LABEL = re.compile(r"\s+(?P<what>(?:[A-Z][A-Z'&-]+\s+)*(?:SCREENING|MEMBERS?|PREVIEW|PREMIERE|Q&A)(?:\s+[A-Z][A-Z'&-]+)*)\s*$")
PRINTS = re.compile(r"\s*[:–—-]\s*(?P<what>(?:new|rare|original)?\s*(?P<mm>35|16|70)\s?mm\s+prints?)!?\s*$", re.I)
REPEATED = 3            # a prefix on this many different titles at one cinema is a series ("EC:", "The Metropolitan Opera:")


def _note(s: Screening, *notes: str | None) -> None:
    s.note = "; ".join(dict.fromkeys(n for n in (*notes, s.note) if n)) or None


def _prefix(title: str) -> tuple[str, str] | None:
    """'Playback: City of God' -> ('Playback', 'City of God'); None when the rest names a part."""
    m = re.match(r"^(?P<pre>[^:]{2,60}?)\s*:\s+(?P<rest>\S.*)$", title)
    if not m or PART.match(m.group("rest")) or re.search(r"\b(?:pgm|program(?:me)?|part|vol)\.?\s*\d*$", m.group("pre"), re.I):
        return None                                  # "Ciprì & Maresco PGM 1: Cinema" names a programme of a series
    return m.group("pre").strip(), m.group("rest").strip()


def series_prefixes(screenings: list[Screening]) -> set[str]:
    """Prefixes shared by REPEATED or more different titles at this cinema."""
    seen: dict[str, set[str]] = {}
    for s in screenings:
        if p := _prefix(s.title):
            seen.setdefault(title_norm(p[0]), set()).add(title_norm(p[1]))
    return {pre for pre, rests in seen.items() if len(rests) >= REPEATED}


def tidy_one(s: Screening, venue: VenueConfig, shared: set[str] = frozenset()) -> None:
    """All the rules above, in order, on one screening (in place)."""
    original = s.title
    places = f"{venue.name} {venue.short or ''} {s.screen or ''}"
    title, fmt, note = tidy_title(s.title, places)
    if title != s.title:
        s.title, s.format = title, s.format or fmt
        _note(s, note)

    if (m := PRESENTER.match(s.title)) and len(m.group("who").split()) <= 7:
        who = m.group("who").strip(" ,")
        s.title = m.group("rest").strip()
        if not (s.series and title_norm(s.series).startswith(title_norm(who))):
            _note(s, f"{who} presents")

    if m := EVENT_PREFIX.match(s.title):
        s.title = m.group("rest").strip()
        if not (s.series and title_norm(m.group("what")) in title_norm(s.series)):
            _note(s, m.group("what"))

    if p := _prefix(s.title):
        pre, rest = p
        own = s.series and title_norm(s.series).startswith(title_norm(pre))
        director = s.director and any(title_norm(pre) == title_norm(d) for d in s.director.split(","))
        if (own or title_norm(pre) in shared) and not director:    # "Sergei Loznitsa: The Early Films" stays
            s.title = rest
            if not s.series:
                s.series = SERIES_ALIASES.get(pre, pre)

    if m := SUPPORT.match(s.title):
        s.title = m.group("main").strip()
        _note(s, f"{m.group('how').capitalize()} by {m.group('short').strip()}")

    if m := RESTORATION.search(s.title):                        # "Network (4K Restoration)"
        s.title = s.title[: m.start()].strip()
        _note(s, m.group("what"))

    if any(c.islower() for c in s.title) and (m := CAPS_LABEL.search(s.title)):
        s.title = s.title[: m.start()].strip()
        _note(s, m.group("what").capitalize())

    if m := PRINTS.search(s.title):                             # "…: New 35mm Prints!"
        s.title, s.format = s.title[: m.start()].strip(), s.format or f"{m.group('mm')}mm"
        _note(s, m.group("what").strip())

    if m := ANNIVERSARY.search(s.title):
        s.title = s.title[: m.start()].strip(" :–—-")
        _note(s, m.group("what"))

    if (m := YEAR.search(s.title)) and (not s.year or s.year == int(m.group(1))):
        s.title, s.year = s.title[: m.start()].strip(), int(m.group(1))

    s.title = drop_director_possessive(s.title, s.director)
    s.title = clean_text(s.title) or original
    if s.title != original and not any(c.islower() for c in s.title):
        s.title = smart_title(s.title)


def tidy(screenings: list[Screening], venue: VenueConfig) -> None:
    shared = series_prefixes(screenings)
    for s in screenings:
        tidy_one(s, venue, shared)


# ---------- review: what still looks like a label ----------
SUSPECT = {
    "presenter": re.compile(r"\bpresents?\b", re.I),
    "support short": re.compile(r"\b(?:preceded|followed) by\b", re.I),
    "event words": re.compile(r"\b(?:q\s*&\s*a|in person|introduc\w+|book launch|screening)\b", re.I),
    # an original title in another script ("The Trial (ПРОЦЕСС)") is the film's name: only Latin brackets
    "brackets": re.compile(r"\[|\((?!aka\b)[\x00-\u024f]*\)\s*$", re.I),
    "all capitals": re.compile(r"^[^a-z]*[A-Z]{4,}[^a-z]*$"),
    "w/": re.compile(r"\bw/", re.I),
}


def audit(rows) -> list[tuple[str, str, str]]:
    """(venue, title, why) for titles that still look like they carry a label, plus prefixes shared by two titles."""
    out = []
    prefixes = Counter()
    for venue_id, title in rows:
        for why, rx in SUSPECT.items():
            if rx.search(title):
                out.append((venue_id, title, why))
        if p := _prefix(title):
            prefixes[(venue_id, title_norm(p[0]))] += 1
    for venue_id, title in rows:
        if (p := _prefix(title)) and prefixes[(venue_id, title_norm(p[0]))] >= 2:
            out.append((venue_id, title, "shared prefix"))
    return sorted(set(out))


REVIEWED = Path(__file__).resolve().parent.parent / "config" / "titles_reviewed.txt"


def reviewed() -> set[tuple[str, str]]:
    """'venue | title' lines already looked at and found to be the film's own name."""
    if not REVIEWED.exists():
        return set()
    out = set()
    for line in REVIEWED.read_text(encoding="utf-8").splitlines():
        if "|" in line and not line.lstrip().startswith("#"):
            v, t = line.split("|", 1)
            out.add((v.strip(), t.strip()))
    return out


def main() -> int:
    from .store import Store
    from .normalize import today_local
    store = Store()
    rows = sorted({(r["venue_id"], r["title"]) for r in store.screenings_since(today_local().isoformat())
                   if not r["venue_id"].startswith("ref-")})
    ok = reviewed()
    found = [f for f in audit(rows) if f[:2] not in ok]
    for venue_id, title, why in found:
        print(f"{venue_id:28} {why:14} {title}")
    print(f"{len(found)} title(s) to look at", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
