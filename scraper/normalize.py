"""Title cleaning, time parsing and stable-id helpers."""
from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "America/New_York"
TZ = ZoneInfo(DEFAULT_TIMEZONE)          # default only; venues carry their own `timezone`

FILM_FORMATS = {"16mm", "35mm", "70mm"}
_FORMAT_CANON = {
    "dcp": "DCP", "35mm": "35mm", "16mm": "16mm", "70mm": "70mm", "8mm": "8mm",
    "super 8": "Super 8", "super8": "Super 8", "vhs": "VHS", "digital": "Digital",
    "digital video": "Digital Video", "blu-ray": "Blu-ray", "bluray": "Blu-ray",
    "dvd": "DVD", "4k dcp": "4K DCP", "2k dcp": "DCP",
}


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def zone(name: str | ZoneInfo | None) -> ZoneInfo:
    """ZoneInfo for an IANA name (None -> the default, America/New_York)."""
    if isinstance(name, ZoneInfo):
        return name
    return ZoneInfo(name) if name else TZ


def today_local(tz: ZoneInfo | str | None = None) -> date:
    return datetime.now(zone(tz)).date()


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


def to_local(dt: datetime, tz: ZoneInfo | str | None = None) -> datetime:
    """Attach / convert to the venue's zone (default America/New_York). Naive datetimes are assumed local."""
    z = zone(tz)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=z)
    return dt.astimezone(z)


def iso(dt: datetime, tz: ZoneInfo | str | None = None) -> str:
    return to_local(dt, tz).replace(microsecond=0).isoformat()


def parse_iso(s: str, tz: ZoneInfo | str | None = None) -> datetime:
    return to_local(datetime.fromisoformat(s), tz)


def end_from_runtime(start: datetime, runtime_min: int | None, tz: ZoneInfo | str | None = None) -> str | None:
    """start + runtime, rendered in `tz` (default: start's own zone if it has one, else the default zone)."""
    if not runtime_min:
        return None
    if tz is None and isinstance(start.tzinfo, ZoneInfo):
        tz = start.tzinfo
    return iso(start + timedelta(minutes=runtime_min), tz)


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
        m = re.match(r"^([\W_]*)(.*?)([^\w&]*)$", w)    # letters in any script: KANAŁ, KATYŃ, ŁÓDŹ
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


def title_case_runs(s: str | None) -> str | None:
    """smart_title for titles that are only partly in capitals: 'MY UNDESIRABLE FRIENDS: PART II – EXILE:
    Chapters 1-3' -> 'My Undesirable Friends: Part II – Exile: Chapters 1-3'. Runs of upper-case words (two or
    more, or one word of five letters or more) are title-cased; mixed-case words and short acronyms stay."""
    s = clean_text(s)
    if not s or not any(c.islower() for c in s):
        return smart_title(s)
    words = s.split(" ")
    is_caps = [bool(re.search(r"[A-Z]", w)) and not re.search(r"[a-z]", w) for w in words]
    out, i = [], 0
    while i < len(words):
        if not is_caps[i]:
            out.append(words[i])
            i += 1
            continue
        j = i
        while j < len(words) and is_caps[j]:
            j += 1
        run = " ".join(words[i:j])
        out.append(smart_title(run) if j - i >= 2 or len(re.sub(r"\W", "", run)) >= 5 else run)
        i = j
    return " ".join(out)


def language_from_text(text: str | None) -> str | None:
    """'In French, Wolof, and Portuguese Creole with English subtitles' -> 'French, Wolof, Portuguese Creole';
    'silent' / 'with English intertitles' -> 'Silent'. Otherwise None (unknown, not 'English')."""
    if not text:
        return None
    if m := _SUBS.search(text):
        parts = re.split(r",\s*(?:and\s+)?|\s+and\s+", m.group(1), flags=re.I)
        # sites that print credits in capitals ("IN RUSSIAN WITH ENGLISH SUBTITLES") get the same casing
        langs = [p.strip().title() if p.strip().islower() or p.strip().isupper() else p.strip() for p in parts if p.strip()]
        return ", ".join(dict.fromkeys(langs)) or None
    if _SILENT.search(text):
        return "Silent"
    return None


def is_english_primary(language: str | None) -> bool | None:
    """True if the first listed language is English; None if unknown."""
    if not language:
        return None
    return language.split(",")[0].strip().lower() == "english"


# ---------- dates without a year, ISO durations ----------
MONTH_NUMBERS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug",
                                              "sep", "oct", "nov", "dec"], 1)}


def month_number(name: str) -> int | None:
    return MONTH_NUMBERS.get((name or "").strip()[:3].lower())


def nearest_date(month: int, day: int, ref: date, bias_days: int = 30) -> date | None:
    """A month/day without a year: the candidate year that puts it nearest to `ref`, biased toward the
    future (a listing fetched on Dec 28 that says 'Jan 2' means next year)."""
    cands = []
    for y in (ref.year - 1, ref.year, ref.year + 1):
        try:
            cands.append(date(y, month, day))
        except ValueError:
            pass
    return min(cands, key=lambda d: abs((d - ref).days + bias_days)) if cands else None


_DURATION = re.compile(r"^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", re.I)


def iso_duration_minutes(s) -> int | None:
    """'PT2H1M' -> 121, 'PT95M' -> 95; plain numbers are minutes."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return int(s) or None
    s = str(s).strip()
    if s.isdigit():
        return int(s) or None
    m = _DURATION.match(s)
    if not m or not any(m.groups()):
        return None
    d, h, mi, _ = (int(x or 0) for x in m.groups())
    return (d * 1440 + h * 60 + mi) or None


_FORMAT_SUFFIX = re.compile(r"(?:\s*[\(\[]\s*|\s+[-–—:]\s+(?:on\s+|in\s+)?)"
                            r"(35\s?mm|16\s?mm|70\s?mm|8\s?mm|super\s?8|4k(?: dcp| restoration)?|dcp|vhs)"
                            r"(?:\s*[\)\]])?\s*$", re.I)


def split_format_suffix(title: str) -> tuple[str, str | None]:
    """'Idlewild (35mm)' / 'The Misconceived - 35MM' -> (title, '35mm'); '4K restoration' is not a print format."""
    m = _FORMAT_SUFFIX.search(title or "")
    if not m:
        return title, None
    raw = re.sub(r"\s+", " ", m.group(1).lower()).replace("35 mm", "35mm").replace("16 mm", "16mm").replace("70 mm", "70mm")
    fmt = None if "restoration" in raw else normalize_format(raw.replace(" ", "") if raw.endswith("mm") else raw)
    return title[:m.start()].strip(), fmt
