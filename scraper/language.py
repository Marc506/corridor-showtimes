"""Fill Screening.language for sites that don't publish it (Metrograph, FLC, MoMA, Film Forum…).

Order of precedence: what the venue's own site says (set by the scraper) > TMDB lookup > the venue's
`default_language` in venues.yaml. TMDB is optional: put an API Read Access Token (or a v3 API key)
in config/tmdb_token.txt, or set TMDB_TOKEN. Without one, only the first and last steps apply.

TMDB (themoviedb.org) is also where Letterboxd gets its film data. Lookups are cached in
data/cache/tmdb.json: matches forever, misses for 14 days.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from .models import Screening, VenueConfig
from .normalize import title_norm, today_local

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = ROOT / "config" / "tmdb_token.txt"
CACHE_FILE = ROOT / "data" / "cache" / "tmdb.json"
API = "https://api.themoviedb.org/3"
MISS_TTL = timedelta(days=14)
MIN_INTERVAL_S = 0.06              # TMDB allows ~50 req/s; stay far below

# Titles that are events/programmes rather than one film — don't guess a language for them.
NOT_A_FILM = re.compile(r"\b(program(me)?|pgm|shorts|talk|lecture|conversation|workshop|panel|party|"
                        r"reading|masterclass|members only|open house|gala|pass)\b", re.I)
PREFIXES = re.compile(r"^(?:[A-Z]{2,4}:\s+|.{3,60}?\s+[Pp]resents:?\s+|(?:opening|closing|centerpiece)\s+night:\s+|"
                      r"sneak preview:\s+|preview:\s+)", re.I)
SUFFIXES = re.compile(r"\s*(?:\((?:[^)]*restoration[^)]*|\d+k|35mm|16mm|70mm|in \d+mm|director'?s cut)\)|"
                      r"\s+(?:w/|with)\s+.*|\s+in\s+(?:35|16|70)mm)\s*$", re.I)
# Opera/ballet broadcasts (Met Live in HD etc.) are sung in the original language with English
# subtitles; TMDB would match them to an unrelated same-title film ("Macbeth" -> English).
OPERA = re.compile(r"\b(opera|live in hd|met: live|bolshoi|royal ballet)\b", re.I)
OPERA_LANGUAGE = "Opera (subtitled)"
LANG_NAMES_FALLBACK = {"en": "English", "fr": "French", "ja": "Japanese", "zh": "Chinese", "cn": "Cantonese",
                       "ko": "Korean", "de": "German", "it": "Italian", "es": "Spanish", "pt": "Portuguese",
                       "ru": "Russian", "hi": "Hindi", "fa": "Persian", "ar": "Arabic", "sv": "Swedish",
                       "da": "Danish", "no": "Norwegian", "pl": "Polish", "tr": "Turkish", "xx": "No dialogue"}


def load_token() -> str | None:
    tok = os.environ.get("TMDB_TOKEN")
    if not tok and TOKEN_FILE.exists():
        tok = TOKEN_FILE.read_text(encoding="utf-8").strip()
    return tok or None


def search_title(title: str) -> str | None:
    """'EC: Strike' -> 'Strike'; 'Jollof Films Presents: Faat Kiné' -> 'Faat Kiné'; None for programmes."""
    if " + " in title or NOT_A_FILM.search(title):
        return None
    t = PREFIXES.sub("", title).strip()
    # "Ken Russell’s The Devils" -> "The Devils" (only before an article: keeps "Schindler's List")
    t = re.sub(r"^(?:[A-Z][\w.\-]+\s){0,3}[A-Z][\w.\-]+[’']s\s+(?=(?:The|A|An)\s)", "", t)
    t = SUFFIXES.sub("", t).strip(" -–—:")
    return t or None


class TmdbLanguage:
    def __init__(self, token: str):
        self.token = token
        self.client = httpx.Client(timeout=20, headers={"Accept": "application/json"})
        if len(token) == 32 and re.fullmatch(r"[0-9a-f]{32}", token):
            self.auth = {"params": {"api_key": token}}                 # legacy v3 key
        else:
            self.client.headers["Authorization"] = f"Bearer {token}"   # API Read Access Token
            self.auth = {"params": {}}
        self._last = 0.0
        self.cache = self._load()
        self.disabled = False

    # --- http ---------------------------------------------------------------------
    def _get(self, path: str, **params) -> dict:
        wait = self._last + MIN_INTERVAL_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        r = self.client.get(API + path, params={**self.auth["params"], **params})
        if r.status_code == 401:
            self.disabled = True
            raise RuntimeError("TMDB rejected the token (401) — check config/tmdb_token.txt")
        if r.status_code == 429:
            time.sleep(2)
            r = self.client.get(API + path, params={**self.auth["params"], **params})
        r.raise_for_status()
        return r.json()

    # --- cache --------------------------------------------------------------------
    def _load(self) -> dict:
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return {"languages": {}, "films": {}}

    def save(self) -> None:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1), encoding="utf-8")

    def language_name(self, code: str) -> str:
        names = self.cache.setdefault("languages", {})
        if not names:
            try:
                for l in self._get("/configuration/languages"):
                    names[l["iso_639_1"]] = l.get("english_name") or l["iso_639_1"]
                names["xx"] = "No dialogue"
            except Exception as e:  # noqa: BLE001
                log.warning("TMDB language list unavailable (%s)", e)
        return names.get(code) or LANG_NAMES_FALLBACK.get(code) or code

    # --- lookup -------------------------------------------------------------------
    def lookup(self, title: str, year: int | None, director: str | None) -> str | None:
        q = search_title(title)
        if not q:
            return None
        key = f"{title_norm(q)}|{year or ''}"
        hit = self.cache["films"].get(key)
        if hit:
            if hit.get("lang") or datetime.now(timezone.utc) - datetime.fromisoformat(hit["at"]) < MISS_TTL:
                return hit.get("lang")
        lang, tmdb_id = self._find(q, year, director)
        self.cache["films"][key] = {"lang": lang, "id": tmdb_id, "at": datetime.now(timezone.utc).isoformat()}
        return lang

    def _find(self, q: str, year: int | None, director: str | None) -> tuple[str | None, int | None]:
        results = self._get("/search/movie", query=q, include_adult="false").get("results", [])
        want = title_norm(q)
        exact = [m for m in results if want in (title_norm(m.get("title") or ""), title_norm(m.get("original_title") or ""))]
        pool = exact or results[:3]

        def yr(m):
            try:
                return int((m.get("release_date") or "")[:4])
            except ValueError:
                return None

        if year:
            pool = [m for m in pool if yr(m) and abs(yr(m) - year) <= 1]
            exact_year = [m for m in pool if yr(m) == year]
            if len(exact_year) == 1:
                pool = exact_year               # same year beats ±1 neighbours before any credits call
        elif not exact:
            return None, None                   # no year and no exact title: too risky
        if len(pool) > 1 and director:
            pool = [m for m in pool if self._directed_by(m["id"], director)]
        if len(pool) > 1 and not year:
            langs = {m.get("original_language") for m in pool}
            this_year = [m for m in pool if (yr(m) or 0) >= today_local().year]
            recent = [m for m in pool if (yr(m) or 0) >= today_local().year - 2]
            if len(langs) == 1:
                pool = pool[:1]                         # every candidate has the same language: no need to pick
            elif len(this_year) == 1:
                pool = this_year                        # this year's festival premiere
            elif len(recent) == 1:
                pool = recent
            else:
                ranked = sorted(pool, key=lambda m: m.get("popularity") or 0, reverse=True)
                top, second = (ranked[0].get("popularity") or 0), (ranked[1].get("popularity") or 0)
                pool = [ranked[0]] if top >= 3 * max(second, 0.5) else []   # one clearly-famous film
        if not pool:
            return None, None
        m = pool[0]
        code = m.get("original_language")
        return (self.language_name(code) if code else None), m.get("id")

    def _directed_by(self, movie_id: int, director: str) -> bool:
        try:
            crew = self._get(f"/movie/{movie_id}/credits").get("crew", [])
        except Exception:  # noqa: BLE001
            return False
        names = {title_norm(c.get("name") or "") for c in crew if c.get("job") == "Director"}
        return any(title_norm(d) in names for d in re.split(r",|&| and ", director) if d.strip())


def title_hints(rows) -> dict[str, tuple[int | None, str | None]]:
    """search-title -> (year, director) from any venue's screenings, so a title listed without a
    year at one venue (FLC) can borrow it from another (BAM: 'Fatherland', 2026, Pawlikowski)."""
    hints: dict[str, tuple[int | None, str | None]] = {}
    for title, year, director in rows:
        q = search_title(title or "")
        if q and year and title_norm(q) not in hints:
            hints[title_norm(q)] = (year, director)
    return hints


def fill_languages(screenings: list[Screening], venue: VenueConfig, tmdb: TmdbLanguage | None,
                   hints: dict | None = None) -> None:
    """Fill missing languages in place: opera rule, TMDB (if configured), then venue.default_language."""
    stats = {"site": 0, "tmdb": 0, "default": 0, "unknown": 0}
    memo: dict[tuple, str | None] = {}
    for s in screenings:
        if s.language:
            stats["site"] += 1
            continue
        if OPERA.search(s.series or "") or OPERA.search(s.note or ""):
            s.language = OPERA_LANGUAGE
            stats["opera"] = stats.get("opera", 0) + 1
            continue
        if tmdb and not tmdb.disabled:
            year, director = s.year, s.director
            if not year and hints:
                q = search_title(s.title)
                year, director = hints.get(title_norm(q), (None, director)) if q else (None, director)
                director = s.director or director
            k = (s.title, year, director)
            if k not in memo:
                try:
                    memo[k] = tmdb.lookup(s.title, year, director)
                except Exception as e:  # noqa: BLE001 — language is best effort
                    log.warning("[%s] TMDB lookup failed for %r: %s", venue.id, s.title, e)
                    memo[k] = None
            if memo[k]:
                s.language = memo[k]
                stats["tmdb"] += 1
                continue
        if venue.default_language:
            s.language = venue.default_language
            stats["default"] += 1
        else:
            stats["unknown"] += 1
    if tmdb:
        tmdb.save()
    if screenings:
        log.info("[%s] language: %s", venue.id, ", ".join(f"{k} {v}" for k, v in stats.items() if v))
