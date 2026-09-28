"""Venue registry and scraper lookup.

Venues come from config/venues.yaml (v1 or v2, see scraper.config). A venue's `source.adapter` picks
the class: a reusable adapter from scraper/adapters/, or `custom`, which uses the hand-written module
scraper/sources/<module>.py registered with @register("<module>").
"""
from __future__ import annotations

import importlib
from pathlib import Path

from .config import ConfigError, load_venues as _load
from .models import VenueConfig

ROOT = Path(__file__).resolve().parent.parent
VENUES_FILE = ROOT / "config" / "venues.yaml"

_SCRAPERS: dict[str, type] = {}

__all__ = ["ConfigError", "build_fallback", "build_scraper", "get_scraper_class", "load_venues", "register"]


def register(name: str):
    def deco(cls):
        _SCRAPERS[name] = cls
        cls.scraper_name = name
        return cls
    return deco


def load_venues(path: Path | None = None, lang: str | None = None) -> list[VenueConfig]:
    return _load(path or VENUES_FILE, lang)


def get_scraper_class(name: str) -> type:
    """A custom module (scraper/sources/<name>.py) or, failing that, an adapter of that name."""
    if name not in _SCRAPERS:
        try:
            importlib.import_module(f"scraper.sources.{name}")   # module import runs @register
        except ModuleNotFoundError as e:
            if e.name != f"scraper.sources.{name}":
                raise
    if name in _SCRAPERS:
        return _SCRAPERS[name]
    from .adapters import get_adapter_class
    return get_adapter_class(name)


def _class_for(ref: dict) -> type:
    if ref.get("adapter") == "custom":
        return get_scraper_class(ref["module"])
    from .adapters import get_adapter_class
    return get_adapter_class(ref["adapter"])


def build_scraper(venue: VenueConfig, client=None):
    return _class_for(venue.source)(venue, client=client, params=venue.source_params)


def build_fallback(venue: VenueConfig, client=None):
    """The venue's fallback scraper, or None if it has none."""
    if not venue.fallback:
        return None
    params = {k: v for k, v in venue.fallback.items() if k != "adapter"}
    return _class_for(venue.fallback)(venue, client=client, params=params)
