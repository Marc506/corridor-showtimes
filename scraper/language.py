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
from .normalize import end_from_runtime, parse_iso, title_norm, today_local

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = ROOT / "config" / "tmdb_token.txt"
CACHE_FILE = ROOT / "data" / "cache" / "tmdb.json"
API = "https://api.themoviedb.org/3"
MISS_TTL = timedelta(days=14)
CACHE_VERSION = 3                  # 3: identity rules (this year / recent / famous) before language consensus
MIN_INTERVAL_S = 0.06              # TMDB allows ~50 req/s; stay far below

# Titles that are events/programmes rather than one film — don't guess a language for them.
NOT_A_FILM = re.compile(r"\b(program(me)?|pgm|shorts|talk|lecture|conversation|workshop|panel|party|"
                        r"reading|masterclass|members only|open house|gala|pass)\b", re.I)
PREFIXES = re.compile(r"^(?:[A-Z]{2,4}:\s+|.{3,60}?\s+[Pp]resents:?\s+|(?:opening|closing|centerpiece)\s+night:\s+|"
                      r"sneak preview:\s+|preview:\s+)", re.I)
SUFFIXES = re.compile(r"\s*(?:\((?:[^)]*restoration[^)]*|\d+k|35mm|16mm|70mm|in \d+mm|director'?s cut|(?:18|19|20)\d{2})\)|"
                      r":\s*\d+(?:st|nd|rd|th)\s+anniversary\b.*|\s*[-–:]\s*(?:4k\s+)?remaster(?:ed)?\b.*|"
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


def same_person(a: str, b: str) -> bool:
    """Loose name match for directors written differently by a cinema and by TMDB:
    'Oleksandr Dovzhenko' ~ 'Alexander Dovzhenko', 'Stephen Lisberger' ~ 'Steven Lisberger',
    'Tsai Ming-liang' ~ 'Ming-liang Tsai'. Same surname (last word) or a shared word of 4+ letters."""
    ta, tb = title_norm(a).split(), title_norm(b).split()
    if not ta or not tb:
        return False
    if ta == tb or ta[-1] == tb[-1]:
        return True
    return any(len(w) >= 4 for w in set(ta) & set(tb))


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
            cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            cache = {}
        if cache.get("version") != CACHE_VERSION:          # matching rules changed: re-match every film
            cache = {"version": CACHE_VERSION, "languages": cache.get("languages", {}), "films": {}}
        return cache

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
        return (self.details(title, year, director) or {}).get("lang")

    def details(self, title: str, year: int | None, director: str | None) -> dict | None:
        """{'lang', 'id', 'sure', 'directors', 'year'} for a title, or None for programmes / misses.

        `sure` means the match identifies one film (year, director or a unique candidate agreed);
        a match that only knows "every candidate has the same language" is not sure, and then only
        the language may be used — never the director or year.
        """
        q = search_title(title)
        if not q:
            return None
        key = f"{title_norm(q)}|{year or ''}|{title_norm(director or '')}"   # the result depends on all three
        hit = self.cache["films"].get(key)
        now = datetime.now(timezone.utc)
        if hit and not hit.get("lang") and now - datetime.fromisoformat(hit["at"]) < MISS_TTL:
            return None                                 # recent miss
        if not hit or not hit.get("lang") or "sure" not in hit:   # new, expired miss, or cached before directors
            lang, tmdb_id, sure, rel_year = self._find(q, year, director)
            hit = {"lang": lang, "id": tmdb_id, "sure": sure, "year": rel_year, "at": now.isoformat()}
            self.cache["films"][key] = hit
        if hit.get("sure") and hit.get("id") and ("directors" not in hit or "runtime" not in hit):
            hit["directors"], hit["runtime"] = self._film_facts(hit["id"])
        return hit if hit.get("lang") else None

    def _film_facts(self, movie_id: int) -> tuple[list[str], int | None]:
        """Directors and runtime (minutes) in one request: /movie/{id}?append_to_response=credits."""
        try:
            d = self._get(f"/movie/{movie_id}", append_to_response="credits")
        except Exception as e:  # noqa: BLE001 — best effort; retried next run (keys stay absent)
            log.warning("TMDB film details unavailable for %s (%s)", movie_id, e)
            raise
        crew = (d.get("credits") or {}).get("crew", [])
        directors = list(dict.fromkeys(c["name"] for c in crew if c.get("job") == "Director" and c.get("name")))
        runtime = d.get("runtime") or None                 # TMDB uses 0 for "unknown"
        return directors, (runtime if runtime and 1 <= runtime <= 900 else None)

    def _find(self, q: str, year: int | None, director: str | None) -> tuple[str | None, int | None, bool, int | None]:
        results = self._get("/search/movie", query=q, include_adult="false").get("results", [])
        want = title_norm(q)
        names = lambda m: (title_norm(m.get("title") or ""), title_norm(m.get("original_title") or ""))  # noqa: E731
        exact = [m for m in results if want in names(m)]
        if director:
            # cinemas shorten long titles ("You Had to Be There" for "You Had to Be There: How the Toronto
            # Godspell…"); with a director to confirm it, "<title>: …" is a candidate too
            exact += [m for m in results if m not in exact
                      and any((m.get(f) or "").lower().startswith(q.lower() + ":") for f in ("title", "original_title"))]
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
            return None, None, False, None      # no year and no exact title: too risky
        if director:
            # the cinema names the director: a candidate by someone else is a different film, even if it
            # is the only one with this title (e.g. a 2012 short vs. the 2026 feature Film Forum shows)
            pool = [m for m in pool if self._directed_by(m["id"], director)]
        sure = True
        if len(pool) > 1 and not year:
            langs = {m.get("original_language") for m in pool}
            this_year = [m for m in pool if (yr(m) or 0) >= today_local().year]
            recent = [m for m in pool if (yr(m) or 0) >= today_local().year - 2]
            ranked = sorted(pool, key=lambda m: m.get("popularity") or 0, reverse=True)
            top, second = (ranked[0].get("popularity") or 0), (ranked[1].get("popularity") or 0)
            # rules that identify the film come first; "they're all in one language" only settles language
            if len(this_year) == 1:
                pool = this_year                        # this year's festival premiere (Paper Tiger, 2026)
            elif len(recent) == 1:
                pool = recent
            elif top >= 3 * max(second, 0.5):
                pool = [ranked[0]]                      # one clearly-famous film
            elif len(langs) == 1:
                pool, sure = pool[:1], False            # same language everywhere: fine for language, not identity
            else:
                pool = []
        if not pool:
            return None, None, False, None
        m = pool[0]
        code = m.get("original_language")
        return (self.language_name(code) if code else None), m.get("id"), sure, yr(m)

    def _directed_by(self, movie_id: int, director: str) -> bool:
        try:
            crew = self._get(f"/movie/{movie_id}/credits").get("crew", [])
        except Exception:  # noqa: BLE001
            return False
        names = [c.get("name") or "" for c in crew if c.get("job") == "Director"]
        return any(same_person(d, n) for d in re.split(r",|&| and ", director) if d.strip() for n in names)


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
    """Fill missing film info in place.

    Language: the site's own text > opera rule > TMDB > venue.default_language.
    Director (and a missing year): only from a TMDB match that is sure to be the same film, and never
    overwriting what the cinema's site says.
    """
    stats = {"site": 0, "tmdb": 0, "default": 0, "unknown": 0}
    memo: dict[tuple, dict | None] = {}
    for s in screenings:
        opera = bool(OPERA.search(s.series or "") or OPERA.search(s.note or ""))
        if not s.language and opera:
            s.language = OPERA_LANGUAGE
            stats["opera"] = stats.get("opera", 0) + 1
        elif s.language:
            stats["site"] += 1
        info = None
        if tmdb and not tmdb.disabled and not opera and (not s.language or not s.director or not s.runtime_min):
            year, director = s.year, s.director
            if not year and hints:
                q = search_title(s.title)
                year, director = hints.get(title_norm(q), (None, director)) if q else (None, director)
                director = s.director or director
            k = (s.title, year, director)
            if k not in memo:
                try:
                    memo[k] = tmdb.details(s.title, year, director)
                except Exception as e:  # noqa: BLE001 — best effort
                    log.warning("[%s] TMDB lookup failed for %r: %s", venue.id, s.title, e)
                    memo[k] = None
            info = memo[k]
        if info and info.get("sure"):
            if not s.director and info.get("directors"):
                s.director = ", ".join(info["directors"][:3])
                stats["director"] = stats.get("director", 0) + 1
            if not s.year and info.get("year") and info["year"] <= today_local().year:
                s.year = info["year"]                   # a future TMDB release date isn't the film's year
            if not s.runtime_min and info.get("runtime"):
                s.runtime_min = info["runtime"]
                stats["runtime"] = stats.get("runtime", 0) + 1
                if not s.end:
                    s.end = end_from_runtime(parse_iso(s.start), s.runtime_min)
        if s.language:
            continue
        if info and info.get("lang"):
            s.language = info["lang"]
            stats["tmdb"] += 1
        elif venue.default_language:
            s.language = venue.default_language
            stats["default"] += 1
        else:
            stats["unknown"] += 1
    if tmdb:
        tmdb.save()
    if screenings:
        log.info("[%s] language: %s", venue.id, ", ".join(f"{k} {v}" for k, v in stats.items() if v))
