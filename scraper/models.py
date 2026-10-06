"""Core data types shared by every scraper, the store and the exporter."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Screening:
    """One screening = one venue x one start time x one programme."""

    id: str
    venue_id: str
    title: str
    start: str                      # ISO 8601 with offset, in the venue's timezone
    day: str                        # local date "YYYY-MM-DD"
    end: str | None = None
    director: str | None = None
    year: int | None = None
    runtime_min: int | None = None
    format: str | None = None
    language: str | None = None     # "Japanese", "French, Wolof", "English", "Silent"; None = unknown
    series: str | None = None
    screen: str | None = None
    note: str | None = None
    detail_url: str | None = None
    ticket_url: str | None = None
    source: str = "primary"         # "primary" | the fallback adapter's name ("screenslate")
    scraped_at: str = ""            # ISO UTC

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class VenueStatus:
    venue_id: str
    status: str                     # "ok" | "stale" | "failed" | "disabled"
    fetched_at: str | None = None   # last successful fetch
    count: int = 0
    horizon_end: str | None = None
    error: str | None = None
    source: str = "primary"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class VenueConfig:
    """One entry of config/venues.yaml (v2 shape; v1 entries are converted on load, see registry)."""

    id: str
    name: str
    scraper: str | None = None             # v1: scraper/sources/<scraper>.py; kept as an alias of source.module
    short: str = ""
    region: str = ""                       # "NYC", "PHL", "LA" … front-end filter (v1 name: city)
    timezone: str = "America/New_York"
    color: str = "#888888"
    website: str | None = None
    source: dict = field(default_factory=dict)       # {adapter: <name>, ...params}
    fallback: dict | None = None                     # {adapter: <name>, ...params} or None
    enabled: bool = True
    screenslate_nid: int | None = None     # v1 alias of fallback: {adapter: screenslate, nid: …}
    horizon_days: int = 30
    rate_limit_s: float = 1.0
    max_requests_per_run: int = 20
    allow_empty: bool = False
    default_language: str | None = None    # last resort when neither the site nor TMDB says
    location: dict | None = None           # {name?, address?, geo: [lat, lon]?, places: [...]} for calendar events
    city: str | None = None                # v1 alias of region
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        self.region = self.region or self.city or "NYC"
        self.city = self.region
        self.timezone = self.timezone or "America/New_York"
        if not self.source and self.scraper:
            self.source = {"adapter": "custom", "module": self.scraper}
        if self.source.get("adapter") == "custom" and not self.scraper:
            self.scraper = self.source.get("module")
        if self.fallback is None and self.screenslate_nid:
            self.fallback = {"adapter": "screenslate", "nid": self.screenslate_nid}
        if self.fallback and self.fallback.get("adapter") == "screenslate" and not self.screenslate_nid:
            self.screenslate_nid = self.fallback.get("nid")

    @property
    def adapter(self) -> str | None:
        return self.source.get("adapter")

    @property
    def source_params(self) -> dict:
        return {k: v for k, v in self.source.items() if k != "adapter"}

    @classmethod
    def from_dict(cls, d: dict) -> "VenueConfig":
        known = {f for f in cls.__dataclass_fields__ if f != "extra"}
        kwargs = {k: v for k, v in d.items() if k in known}
        kwargs["extra"] = {k: v for k, v in d.items() if k not in known}
        return cls(**kwargs)


@dataclass
class RawPage:
    url: str
    body: str
    fetched_at: str
    ext: str = "html"               # "html" | "json"
