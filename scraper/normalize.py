"""Title cleaning, time parsing and stable-id helpers."""
from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")

FILM_FORMATS = {"16mm", "35mm", "70mm"}
_FORMAT_CANON = {
    "dcp": "DCP", "35mm": "35mm", "16mm": "16mm", "70mm": "70mm", "8mm": "8mm",
    "super 8": "Super 8", "super8": "Super 8", "vhs": "VHS", "digital": "Digital",
    "digital video": "Digital Video", "blu-ray": "Blu-ray", "bluray": "Blu-ray",
    "dvd": "DVD", "4k dcp": "4K DCP", "2k dcp": "DCP",
}


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today_local() -> date:
    return datetime.now(TZ).date()


def clean_text(s: str | None) -> str | None:
    """Unescape HTML entities, collapse whitespace; empty -> None."""
    if s is None:
        return None
    s = html.unescape(s).replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def title_norm(title: str) -> str:
    """Lower-cased, accent- and punctuation-free title used in ids and de-duplication."""
    t = unicodedata.normalize("NFKD", title)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return t.strip()


def make_id(venue_id: str, start: str, title: str) -> str:
    return hashlib.sha1(f"{venue_id}|{start}|{title_norm(title)}".encode()).hexdigest()[:16]


def normalize_format(fmt: str | None) -> str | None:
    if not fmt:
        return None
    f = fmt.strip()
    return _FORMAT_CANON.get(f.lower(), f)


def to_local(dt: datetime) -> datetime:
    """Attach / convert to America/New_York. Naive datetimes are assumed local."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def iso(dt: datetime) -> str:
    return to_local(dt).replace(microsecond=0).isoformat()


def parse_iso(s: str) -> datetime:
    return to_local(datetime.fromisoformat(s))


def end_from_runtime(start: datetime, runtime_min: int | None) -> str | None:
    return iso(start + timedelta(minutes=runtime_min)) if runtime_min else None


# ---------- title casing for ALL-CAPS sources (Film Forum, Anthology) ----------
_SMALL = {"a", "an", "the", "and", "but", "or", "for", "nor", "of", "on", "in", "at", "to", "by",
          "with", "vs", "from", "as", "de", "la", "le", "les", "du", "des", "et", "y", "el", "da", "di"}
_KEEP_UPPER = {"USA", "NYC", "NY", "TV", "DJ", "MTV", "BBC", "UK", "US", "USSR", "AFA", "EC", "PGM",
               "NYPD", "FBI", "CIA", "LA", "DC", "AI", "Q&A", "WWII", "WWI", "NYFF", "UFO", "OK", "3D", "4K"}
_NOT_ACRONYM = {"MR", "MRS", "MS", "DR", "ST", "JR", "SR", "SGT", "VS"}
_ROMAN = re.compile(r"^(?=[MDCLXVI])M*(C[MD]|D?C{0,3})(X[CL]|L?X{0,3})(I[XV]|V?I{0,3})$")


def _cap_word(core: str) -> str:
    """'BROTHER'S' -> "Brother's", 'SPIDER-MAN' -> 'Spider-Man'."""
    def one(p: str) -> str:
        p = p[:1].upper() + p[1:].lower()
        if len(p) > 2 and p[0] in "OD" and p[1] in "'’":          # O'Connor, D'Arcy
            p = p[:2] + p[2].upper() + p[3:]
        return p
    return "-".join(one(p) for p in core.split("-"))


def smart_title(s: str | None) -> str | None:
    """Title-case a string only if it is entirely upper-case; leave mixed case alone."""
    if not s or any(c.islower() for c in s):
        return s
    words = re.split(r"( |…)", s)
    out = []
    after_break = True                      # start of title, or after ':' / '—' / '+'
    for w in words:
        if w in (" ", "…", ""):
            out.append(w)
            continue
        m = re.match(r"^([^A-Za-z0-9À-ÿ]*)(.*?)([^A-Za-z0-9À-ÿ&]*)$", w)
        lead, core, trail = m.groups() if m else ("", w, "")
        bare = core.replace(".", "")
        if not core:
            out.append(w)
        elif core in _KEEP_UPPER or (_ROMAN.match(bare) and bare not in {"I", "MIX", "MID", "DIM", "LID", "CID", "DID", "MILD", "CIVIL", "LIVID", "VIVID"} or bare == "I"):
            out.append(lead + core + trail)
        elif (bare.isalpha() and len(bare) >= 2 and not re.search(r"[AEIOUYÀ-ÿ]", bare)
              and bare not in _NOT_ACRONYM):
            out.append(lead + core + trail)              # vowel-less: NYPD, PGM, TV …
        elif core.lower() in _SMALL and not after_break and not lead:
            out.append(lead + core.lower() + trail)
        else:
            out.append(lead + _cap_word(core) + trail)
        after_break = bool(re.search(r"[:—–+/!?]$", w)) or w in {"-", "—", "–", "+", "/"}
    return "".join(out)


# ---------- language ----------
_SUBS = re.compile(r"\bin\s+(.+?)\s+with\s+(?:English\s+)?(?:subtitles|subs)\b", re.I)
_SILENT = re.compile(r"\bsilent\b|\bintertitles\b", re.I)


def language_from_text(text: str | None) -> str | None:
    """'In French, Wolof, and Portuguese Creole with English subtitles' -> 'French, Wolof, Portuguese Creole';
    'silent' / 'with English intertitles' -> 'Silent'. Otherwise None (unknown, not 'English')."""
    if not text:
        return None
    if m := _SUBS.search(text):
        parts = re.split(r",\s*(?:and\s+)?|\s+and\s+", m.group(1))
        langs = [p.strip().title() if p.strip().islower() else p.strip() for p in parts if p.strip()]
        return ", ".join(dict.fromkeys(langs)) or None
    if _SILENT.search(text):
        return "Silent"
    return None


def is_english_primary(language: str | None) -> bool | None:
    """True if the first listed language is English; None if unknown."""
    if not language:
        return None
    return language.split(",")[0].strip().lower() == "english"
