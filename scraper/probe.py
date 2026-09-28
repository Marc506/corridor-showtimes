"""SiteProbe: a small, polite look at a cinema's website that adapters' detect() methods read from.

It fetches the URL the user gave plus the site's home page (and, on request, a few common schedule
paths), and records for every response: status, Content-Type, whether it is a firewall challenge,
how many showtime-like tokens the HTML contains, outbound link domains and JSON-LD types.

Limits (ARCHITECTURE §5.7): at most 12 requests per probe, 2 s between requests to one host, no retries.
A 403 / 429 / challenge page stops all further requests to that host — never retried, never worked
around (PLATFORMS.md §12).

Offline use (tests, re-running detection on saved pages)::

    probe = SiteProbe.offline("https://nitehawkcinema.com/williamsburg/", {
        "https://nitehawkcinema.com/williamsburg/": "tests/fixtures/platforms/filmbot/nitehawk_home.html",
        "https://nitehawkcinema.com/williamsburg/wp-json/nj/v1/showtime/listings": ("…listings.json", "application/json"),
    })

URLs not in the mapping answer 404, so a detect() that asks for something unexpected simply finds nothing.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128 Safari/537.36")
MAX_REQUESTS = 12
MIN_INTERVAL_S = 2.0
COMMON_PATHS = ["/calendar", "/showtimes", "/now-playing", "/films", "/schedule", "/events"]

TIME_TOKEN = re.compile(r"\b(?:[01]?\d(?::[0-5]\d)?\s*(?:[ap]\.?m\.?)|\d{4}-\d{2}-\d{2}T\d{2}:\d{2})(?![a-z])", re.I)

CHALLENGES = [
    ("cloudflare", re.compile(r"<title>\s*(just a moment|attention required)|challenges\.cloudflare\.com|cf-browser-verification", re.I)),
    ("sucuri", re.compile(r"sucuri_cloudproxy|sucuri\.net/", re.I)),
    ("incapsula", re.compile(r"_Incapsula_Resource|Incapsula incident", re.I)),
    ("waf", re.compile(r"Bad Bot Request|SiteDistrict|Request unsuccessful\. Incapsula", re.I)),
]


@dataclass
class ProbeResponse:
    url: str
    status: int
    content_type: str = ""
    text: str = ""
    final_url: str = ""
    headers: dict = field(default_factory=dict)
    error: str | None = None            # network error text; status is 0 then

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300 and not self.challenge

    @property
    def is_json(self) -> bool:
        if "json" not in self.content_type.lower():
            return False
        try:
            json.loads(self.text)
        except ValueError:
            return False
        return True

    def json(self):
        return json.loads(self.text)

    @property
    def is_html(self) -> bool:
        ct = self.content_type.lower()
        return "html" in ct or (not ct and self.text.lstrip()[:1] == "<")

    @property
    def challenge(self) -> str | None:
        """'cloudflare' / 'sucuri' / 'incapsula' / 'waf' if this is a firewall page, else None."""
        if self.headers.get("cf-mitigated", "").lower() == "challenge":
            return "cloudflare"
        if "sucuri" in self.headers.get("server", "").lower() and self.status in (307, 403):
            return "sucuri"
        if self.status not in (200, 202, 403, 429, 503) or len(self.text) > 60000:
            return None                      # real pages are long; challenge pages are short
        for name, rx in CHALLENGES:
            if rx.search(self.text):
                return name
        return None

    @property
    def time_tokens(self) -> int:
        if not self.is_html or not self.text:
            return 0
        return len(TIME_TOKEN.findall(visible_text(self.text)))


def visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    return soup.get_text(" ")


def jsonld_objects(html: str) -> list[dict]:
    """Every typed JSON-LD object on the page, including nested ones (@graph, "graph", itemListElement …)."""
    out: list[dict] = []
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(m.group(1).strip())
        except ValueError:
            continue
        stack = [data]
        while stack:
            obj = stack.pop(0)
            if isinstance(obj, list):
                stack.extend(obj)
            elif isinstance(obj, dict):
                if "@type" in obj:
                    out.append(obj)
                stack.extend(v for v in obj.values() if isinstance(v, (dict, list)))
    return out


def ld_types(obj: dict) -> set[str]:
    t = obj.get("@type")
    return set(t) if isinstance(t, list) else {t} if t else set()


class SiteProbe:
    def __init__(self, url: str, *, max_requests: int = MAX_REQUESTS, min_interval: float = MIN_INTERVAL_S,
                 fetcher=None):
        self.url = url if "://" in url else f"https://{url}"
        p = urlparse(self.url)
        self.base = f"{p.scheme}://{p.netloc}"
        self.max_requests = max_requests
        self.min_interval = min_interval
        self.requests = 0
        self.responses: dict[str, ProbeResponse] = {}
        self.stopped_hosts: dict[str, str] = {}      # host -> why we stopped asking it
        self.hints: list[str] = []                   # adapter notes for the wizard, e.g. "agile_no_feed_guid"
        self.log: list[str] = []
        self._fetcher = fetcher
        self._client = None
        self._last_hit: dict[str, float] = {}

    # --- construction -------------------------------------------------------------------
    @classmethod
    def offline(cls, url: str, pages: dict) -> "SiteProbe":
        """pages: {url: path | (path, content_type) | (path, content_type, status) | ProbeResponse}."""
        table: dict[str, ProbeResponse] = {}
        for u, spec in pages.items():
            if isinstance(spec, ProbeResponse):
                table[u] = spec
                continue
            path, ctype, status = (spec, None, 200) if isinstance(spec, (str, Path)) else (tuple(spec) + (200,))[:3]
            text = Path(path).read_text(encoding="utf-8")
            if ctype is None:
                ctype = {".json": "application/json", ".ics": "text/calendar", ".js": "application/javascript",
                         ".xml": "application/xml"}.get(Path(path).suffix, "text/html; charset=utf-8")
            table[u] = ProbeResponse(url=u, status=status, content_type=ctype, text=text, final_url=u)

        def fetch(u: str) -> ProbeResponse:
            return table.get(u) or table.get(u.rstrip("/")) or table.get(u.rstrip("/") + "/") or \
                ProbeResponse(url=u, status=404, content_type="text/html", text="", final_url=u)
        return cls(url, min_interval=0, fetcher=fetch)

    # --- network --------------------------------------------------------------------------
    def _http(self, url: str) -> ProbeResponse:
        import httpx
        if self._client is None:
            self._client = httpx.Client(headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
                                        timeout=20, follow_redirects=True)
        host = urlparse(url).netloc
        wait = self._last_hit.get(host, 0) + self.min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_hit[host] = time.monotonic()
        try:
            r = self._client.get(url)
        except httpx.HTTPError as e:
            return ProbeResponse(url=url, status=0, error=str(e)[:200], final_url=url)
        return ProbeResponse(url=url, status=r.status_code, content_type=r.headers.get("content-type", ""),
                             text=r.text, final_url=str(r.url), headers={k.lower(): v for k, v in r.headers.items()})

    def get(self, url: str) -> ProbeResponse | None:
        """GET once (cached). None when the request budget is spent or the host already refused us."""
        url = urljoin(self.url, url)
        if url in self.responses:
            return self.responses[url]
        host = urlparse(url).netloc
        if host in self.stopped_hosts:
            return None
        if self.requests >= self.max_requests:
            self.log.append(f"budget spent, skipped {url}")
            return None
        self.requests += 1
        r = (self._fetcher or self._http)(url)
        self.responses[url] = r
        self.log.append(f"GET {url} -> {r.status or r.error} {r.content_type.split(';')[0]}"
                        + (f" [{r.challenge}]" if r.challenge else ""))
        if r.challenge or r.status in (403, 429):
            self.stopped_hosts[host] = r.challenge or f"HTTP {r.status}"
        return r

    def close(self) -> None:
        if self._client is not None:
            self._client.close()

    # --- the standard look ------------------------------------------------------------------
    def start(self) -> "SiteProbe":
        """The user's URL, then the home page."""
        self.get(self.url)
        if self.url.rstrip("/") != self.base:
            self.get(self.base + "/")
        return self

    def explore(self) -> None:
        """Common schedule paths — only worth it when the first pages show no showtimes."""
        for path in COMMON_PATHS:
            if self.requests >= self.max_requests - 2:     # keep a little budget for detect()
                break
            self.get(self.base + path)

    # --- what the pages say ----------------------------------------------------------------
    @property
    def pages(self) -> list[ProbeResponse]:
        """HTML pages that loaded (not challenges), in fetch order."""
        return [r for r in self.responses.values() if r.ok and r.is_html]

    @property
    def main(self) -> ProbeResponse | None:
        r = self.responses.get(self.url)
        return r if r and r.ok else (self.pages[0] if self.pages else None)

    @property
    def html(self) -> str:
        return "\n".join(r.text for r in self.pages)

    def find(self, pattern: str, flags=re.I) -> re.Match | None:
        rx = re.compile(pattern, flags)
        for r in self.pages:
            if m := rx.search(r.text):
                return m
        return None

    def findall(self, pattern: str, flags=re.I) -> list:
        rx = re.compile(pattern, flags)
        return list(dict.fromkeys(m for r in self.pages for m in rx.findall(r.text)))

    def links(self) -> list[str]:
        out = []
        for r in self.pages:
            soup = BeautifulSoup(r.text, "lxml")
            for a in soup.find_all(["a", "link", "iframe", "script"]):
                href = a.get("href") or a.get("src")
                if href and not href.startswith(("javascript:", "mailto:", "tel:", "#")):
                    out.append(urljoin(r.final_url or r.url, href.replace("&#038;", "&")))
        return list(dict.fromkeys(out))

    def domains(self) -> set[str]:
        return {urlparse(u).netloc.lower() for u in self.links() if urlparse(u).netloc}

    def wp_roots(self) -> list[str]:
        """WordPress REST roots ("https://site/branch/wp-json/") advertised by the pages, else guessed."""
        roots = self.findall(r'<link[^>]+rel=["\']https://api\.w\.org/["\'][^>]+href=["\']([^"\']+)')
        roots = [r if r.endswith("/") else r + "/" for r in roots]
        if not roots and self.find(r"/wp-content/|/wp-json/|wp-includes"):
            roots = [self.base + "/wp-json/"]
        return list(dict.fromkeys(roots))

    def jsonld(self) -> list[dict]:
        return [o for r in self.pages for o in jsonld_objects(r.text)]

    @property
    def time_tokens(self) -> int:
        return sum(r.time_tokens for r in self.pages)

    @property
    def blocked(self) -> str | None:
        """The challenge / refusal on the user's own site, if every page there was refused."""
        own = [r for u, r in self.responses.items() if urlparse(u).netloc == urlparse(self.url).netloc]
        if own and not any(r.ok for r in own):
            for r in own:
                if r.challenge or r.status in (403, 429):
                    return r.challenge or f"HTTP {r.status}"
        return None

    def evidence(self) -> dict:
        return {
            "url": self.url, "requests": self.requests,
            "responses": [{"url": r.url, "status": r.status, "content_type": r.content_type.split(";")[0],
                           "challenge": r.challenge, "time_tokens": r.time_tokens, "error": r.error}
                          for r in self.responses.values()],
            "blocked": self.blocked, "time_tokens": self.time_tokens,
            "jsonld_types": sorted({t for o in self.jsonld() for t in ld_types(o) if isinstance(t, str)}),
            "hints": self.hints, "log": self.log,
        }
