"""BaseScraper, the shared HTTP client (UA, retries, per-domain rate limit) and raw snapshots."""
from __future__ import annotations

import logging
import time
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .models import RawPage, Screening, VenueConfig, VenueStatus
from .normalize import TZ, make_id, now_utc_iso, today_local, zone

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
CACHE_DIR = ROOT / "data" / "cache"
DETAIL_TTL = timedelta(days=7)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128 Safari/537.36")


class ScrapeError(Exception):
    """Any failure that should mark the venue as failed/stale."""


class RateLimited(ScrapeError):
    """HTTP 429: stop this venue immediately, never retry."""


class _Resp:
    """Minimal response shared by the httpx and curl transports."""

    def __init__(self, status_code: int, text: str, url: str):
        self.status_code, self.text, self.url = status_code, text, url


class HttpClient:
    """GET with desktop UA, retries (5xx / network), per-host rate limit, and 429 = stop.

    transport="curl" shells out to the system curl: some WAFs (screenslate's) reject Python's
    TLS handshake outright but serve curl normally. Only used where a source asks for it.
    """
    RETRIES = 3

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self._client = httpx.Client(
            headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
            timeout=timeout,
            follow_redirects=True,
        )
        self._last_hit: dict[str, float] = {}

    def _throttle(self, url: str, min_interval: float) -> None:
        host = urlparse(url).netloc
        wait = self._last_hit.get(host, 0) + min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_hit[host] = time.monotonic()

    def _curl(self, url: str, headers: dict | None = None) -> _Resp:
        import subprocess
        marker = "\n__CURL_STATUS__"
        extra = [a for k, v in (headers or {}).items() for a in ("-H", f"{k}: {v}")]
        proc = subprocess.run(
            ["curl", "-sS", "-L", "--compressed", "-m", str(int(self.timeout)),
             "-A", UA, "-H", "Accept-Language: en-US,en;q=0.9", *extra,
             "-w", marker + "%{http_code} %{url_effective}", url],
            capture_output=True, text=True)
        if proc.returncode != 0:
            raise httpx.TransportError(f"curl exit {proc.returncode}: {proc.stderr.strip()[:200]}")
        body, _, tail = proc.stdout.rpartition(marker)
        status, _, final = tail.partition(" ")
        return _Resp(int(status), body, final or url)

    def get(self, url: str, *, min_interval: float = 0.0, params: dict | None = None,
            transport: str = "httpx", headers: dict | None = None) -> _Resp:
        if params:
            url = str(httpx.URL(url, params=params))
        last_exc: Exception | None = None
        for attempt in range(self.RETRIES + 1):
            self._throttle(url, min_interval)
            try:
                if transport == "curl":
                    r = self._curl(url, headers)
                else:
                    hr = self._client.get(url, headers=headers)
                    r = _Resp(hr.status_code, hr.text, str(hr.url))
            except httpx.HTTPError as e:
                last_exc = e
                log.warning("GET %s failed (%s), attempt %d", url, e, attempt + 1)
            else:
                if r.status_code == 429:
                    raise RateLimited(f"429 Too Many Requests: {url}")
                if r.status_code < 500:
                    if r.status_code >= 400:
                        raise ScrapeError(f"HTTP {r.status_code}: {url}")
                    return r
                last_exc = ScrapeError(f"HTTP {r.status_code}: {url}")
                log.warning("GET %s -> %d, attempt %d", url, r.status_code, attempt + 1)
            if attempt < self.RETRIES:
                time.sleep(2 ** attempt)
        raise ScrapeError(str(last_exc))

    def close(self) -> None:
        self._client.close()


class BrowserSession:
    """One shared Chromium (Playwright) per run, with a persistent profile in data/browser_profile/
    so Cloudflare's cf_clearance cookie survives between runs (ARCHITECTURE §5.3)."""

    PROFILE = ROOT / "data" / "browser_profile"
    CHALLENGE_MARKERS = ("just a moment", "attention required", "verify you are human")

    def __init__(self, headless: bool = True, challenge_timeout_s: float = 30,
                 timezone_id: str = "America/New_York"):
        self.headless = headless
        self.challenge_timeout_s = challenge_timeout_s
        self.timezone_id = timezone_id
        self._pw = self._ctx = None

    def _ensure(self):
        if self._ctx is None:
            from playwright.sync_api import sync_playwright
            self.PROFILE.mkdir(parents=True, exist_ok=True)
            self._pw = sync_playwright().start()
            self._ctx = self._pw.chromium.launch_persistent_context(
                str(self.PROFILE), headless=self.headless, locale="en-US",
                timezone_id=self.timezone_id, viewport={"width": 1280, "height": 900})
        return self._ctx

    def get_html(self, url: str) -> tuple[str, str]:
        """Open url, wait out a Cloudflare interstitial for up to challenge_timeout_s, return (final_url, html).
        Browser-level problems (window closed by the user, crash, profile in use, timeouts) become a
        one-line ScrapeError so the venue falls back cleanly instead of logging a traceback."""
        from playwright.sync_api import Error as PlaywrightError
        page = None
        try:
            page = self._ensure().new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            deadline = time.monotonic() + self.challenge_timeout_s
            while any(m in page.title().lower() for m in self.CHALLENGE_MARKERS):
                if time.monotonic() > deadline:
                    raise ScrapeError(f"Cloudflare challenge not passed within {self.challenge_timeout_s:.0f}s: {url}")
                page.wait_for_timeout(1000)
            try:
                page.wait_for_load_state("load", timeout=20000)
            except PlaywrightError:     # analytics can keep "load" pending; the content is there
                pass
            page.wait_for_timeout(800)
            return page.url, page.content()
        except PlaywrightError as e:
            msg = str(e).splitlines()[0]
            if "closed" in msg.lower():
                msg = "browser window was closed before the page loaded (closed by hand?)"
            raise ScrapeError(f"browser: {msg}") from None
        finally:
            if page is not None:
                try:
                    page.close()
                except PlaywrightError:
                    pass

    def close(self) -> None:
        for step in (lambda: self._ctx and self._ctx.close(), lambda: self._pw and self._pw.stop()):
            try:
                step()
            except Exception:  # noqa: BLE001 — already closed / crashed
                pass
        self._ctx = self._pw = None


class BrowserDisabled(ScrapeError):
    """CINEMA_NO_BROWSER=1 (CI): browser-only sources fail fast so the venue falls back / goes stale."""


def browser_disabled() -> bool:
    import os
    return os.environ.get("CINEMA_NO_BROWSER", "").strip() not in ("", "0", "false")


class RequestBudgetExceeded(ScrapeError):
    """More GETs than the venue's max_requests_per_run: a paging rule is probably looping."""


class BaseScraper:
    scraper_name: str = ""
    needs_browser: bool = False
    # adapter metadata (see scraper.adapters); hand-written sources leave these alone
    PARAMS: dict[str, type] = {}
    OPTIONAL_PARAMS: dict[str, type] = {}
    DETECT_ORDER: int = 100
    enforce_budget: bool = False          # adapters: stop after venue.max_requests_per_run GETs

    def __init__(self, venue: VenueConfig, client: HttpClient | None = None, params: dict | None = None):
        self.venue = venue
        self.client = client or HttpClient()
        self.params = dict(params if params is not None else venue.source_params)
        self.tz = zone(venue.timezone)
        self.requests_made = 0

    @classmethod
    def detect(cls, probe) -> "object | None":
        """Adapters: return a scraper.adapters.Candidate if `probe` (scraper.detect.SiteProbe) shows this platform."""
        return None

    # --- to implement per source -------------------------------------------------
    def fetch(self) -> list[RawPage]:
        """Network IO only."""
        raise NotImplementedError

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        """Pure function of the fetched pages; must work offline on fixtures."""
        raise NotImplementedError

    def enrich(self, screenings: list[Screening]) -> None:
        """Optional: fill director/year/runtime from detail pages (see detail_info). Never fatal."""

    # --- detail-page cache ------------------------------------------------------------
    def detail_info(self, url: str, parse_detail) -> dict | None:
        """Return parse_detail(html) for a detail page, GETting it at most once per DETAIL_TTL.

        Raw HTML is cached under data/cache/<venue>/ (not the parsed dict), so parser fixes
        apply to cached pages immediately. Raises RateLimited so the caller can stop enriching.
        """
        import hashlib
        path = CACHE_DIR / self.venue.id / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".html")
        fresh = path.exists() and time.time() - path.stat().st_mtime < DETAIL_TTL.total_seconds()
        if fresh:
            html = path.read_text(encoding="utf-8")
        else:
            try:
                html = self.get_page(url).body
            except RateLimited:
                raise
            except ScrapeError as e:
                log.warning("[%s] detail page failed: %s", self.venue.id, e)
                if not path.exists():
                    return None
                html = path.read_text(encoding="utf-8")      # stale copy beats nothing
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(html, encoding="utf-8")
        try:
            return parse_detail(html)
        except Exception:  # noqa: BLE001
            log.exception("[%s] could not parse detail page %s", self.venue.id, url)
            return None

    def enrich_by_url(self, screenings: list[Screening], parse_detail, fields=("director", "year", "runtime_min")) -> None:
        """Common enrich(): one detail GET per distinct detail_url, copy missing fields, derive `end`."""
        from .normalize import end_from_runtime, parse_iso
        urls = list(dict.fromkeys(s.detail_url for s in screenings if s.detail_url))
        info: dict[str, dict] = {}
        for url in urls:
            try:
                data = self.detail_info(url, parse_detail)
            except RateLimited as e:
                log.warning("[%s] %s — stop enriching", self.venue.id, e)
                break
            if data:
                info[url] = data
        for s in screenings:
            data = info.get(s.detail_url) or {}
            for f in fields:
                if getattr(s, f) is None and data.get(f) is not None:
                    setattr(s, f, data[f])
            if s.end is None and s.runtime_min:
                s.end = end_from_runtime(parse_iso(s.start, self.tz), s.runtime_min)

    # --- helpers --------------------------------------------------------------------
    transport: str = "httpx"             # "curl" for WAFs that reject Python's TLS (see HttpClient)

    def browser_page(self, url: str) -> RawPage:
        """Fetch through the shared Playwright browser (needs_browser scrapers)."""
        if browser_disabled():
            raise BrowserDisabled("browser disabled (CINEMA_NO_BROWSER=1)")
        if not hasattr(self, "_browser"):
            opts = self.venue.extra.get("browser") or {}
            self._browser = BrowserSession(headless=opts.get("headless", True),
                                           challenge_timeout_s=opts.get("challenge_timeout_s", 30),
                                           timezone_id=self.venue.timezone)
        self.count_request()
        wait = getattr(self, "_last_browser_hit", 0) + self.venue.rate_limit_s - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        final_url, html = self._browser.get_html(url)
        self._last_browser_hit = time.monotonic()
        return RawPage(url=final_url, body=html, fetched_at=now_utc_iso(), ext="html")

    def close(self) -> None:
        if hasattr(self, "_browser"):
            self._browser.close()

    def count_request(self) -> None:
        self.requests_made += 1
        if self.enforce_budget and self.requests_made > self.venue.max_requests_per_run:
            raise RequestBudgetExceeded(
                f"more than max_requests_per_run={self.venue.max_requests_per_run} requests this run")

    def get_page(self, url: str, ext: str = "html", params: dict | None = None,
                 headers: dict | None = None) -> RawPage:
        self.count_request()
        kw = {"headers": headers} if headers else {}
        r = self.client.get(url, min_interval=self.venue.rate_limit_s, params=params,
                            transport=self.transport, **kw)
        return RawPage(url=str(r.url), body=r.text, fetched_at=now_utc_iso(), ext=ext)

    @property
    def raw_name(self) -> str:
        return self.venue.id

    def save_raw(self, pages: list[RawPage]) -> None:
        day_dir = RAW_DIR / today_local().isoformat()
        day_dir.mkdir(parents=True, exist_ok=True)
        for i, p in enumerate(pages):
            suffix = "" if i == 0 else f"_{i}"
            (day_dir / f"{self.raw_name}{suffix}.{p.ext}").write_text(p.body, encoding="utf-8")

    # --- template method ------------------------------------------------------------
    source: str = "primary"

    def run(self, save_raw: bool = True) -> tuple[list[Screening], VenueStatus]:
        source = self.source
        try:
            pages = self.fetch()
            if save_raw:
                self.save_raw(pages)
            screenings = dedupe(self.parse(pages))
        except ScrapeError as e:
            log.error("[%s] scrape failed: %s", self.venue.id, e)
            self.close()
            return [], VenueStatus(self.venue.id, "failed", error=f"{type(e).__name__}: {e}"[:500], source=source)
        except Exception as e:  # noqa: BLE001 — any failure is isolated to this venue
            log.exception("[%s] scrape failed", self.venue.id)
            self.close()
            return [], VenueStatus(self.venue.id, "failed", error=f"{type(e).__name__}: {e}"[:500], source=source)
        try:
            self.enrich(screenings)
        except Exception:  # noqa: BLE001 — enrichment is best effort
            log.exception("[%s] enrich failed (screenings kept)", self.venue.id)
        finally:
            self.close()
        return screenings, VenueStatus(
            self.venue.id, "ok", fetched_at=now_utc_iso(), count=len(screenings),
            horizon_end=max((s.day for s in screenings), default=None), source=source,
        )


def ref_date(page: RawPage, tz=None):
    """Venue-local date a page was fetched — the anchor for sites that omit month/year."""
    return datetime.fromisoformat(page.fetched_at.replace("Z", "+00:00")).astimezone(zone(tz)).date()


def dedupe(screenings: list[Screening]) -> list[Screening]:
    """One row per screening. The id covers venue, start and title, so a film starting at the same time on
    two screens (or in two buildings) shares one id: those are kept apart when their `screen` names differ.
    The screen that sorts first keeps the plain id, the others get one that also covers the screen, so the
    ids stay the same from run to run. Same id with the same (or no) screen is the same screening twice."""
    groups: dict[str, list[Screening]] = {}
    for s in screenings:
        groups.setdefault(s.id, []).append(s)
    out = []
    for sid, group in groups.items():
        rooms: dict[str, Screening] = {}
        for s in group:
            rooms.setdefault((s.screen or "").strip().lower(), s)
        named = sorted(k for k in rooms if k)
        if len(named) < 2:
            out.append(group[0])
            continue
        out.append(rooms[named[0]])
        for k in named[1:]:
            s = rooms[k]
            out.append(replace(s, id=make_id(s.venue_id, s.start, f"{s.title} @ {s.screen}")))
    return sorted(out, key=lambda s: (s.start, s.title, s.screen or ""))
