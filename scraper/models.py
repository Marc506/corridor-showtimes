"""Core data types shared by every scraper, the store and the exporter."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Screening:
    """One screening = one venue x one start time x one programme."""

    id: str
    venue_id: str
    title: str
    start: str                      # ISO 8601 with offset, America/New_York
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
    source: str = "primary"         # "primary" | "screenslate"
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
    id: str
    name: str
    scraper: str
    short: str = ""
    city: str = "NYC"
    color: str = "#888888"
    enabled: bool = True
    screenslate_nid: int | None = None
    horizon_days: int = 30
    rate_limit_s: float = 1.0
    allow_empty: bool = False
    default_language: str | None = None    # last resort when neither the site nor TMDB says
    extra: dict = field(default_factory=dict)

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
