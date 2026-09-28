"""Scraper registry: @register("id") on a BaseScraper subclass; venues come from config/venues.yaml."""
from __future__ import annotations

import importlib
from pathlib import Path

import yaml

from .models import VenueConfig

ROOT = Path(__file__).resolve().parent.parent
VENUES_FILE = ROOT / "config" / "venues.yaml"

_SCRAPERS: dict[str, type] = {}


def register(name: str):
    def deco(cls):
        _SCRAPERS[name] = cls
        cls.scraper_name = name
        return cls
    return deco


def load_venues(path: Path = VENUES_FILE) -> list[VenueConfig]:
    with open(path, encoding="utf-8") as f:
        items = yaml.safe_load(f) or []
    return [VenueConfig.from_dict(d) for d in items]


def get_scraper_class(name: str) -> type:
    if name not in _SCRAPERS:
        importlib.import_module(f"scraper.sources.{name}")   # module import runs @register
    return _SCRAPERS[name]


def build_scraper(venue: VenueConfig, client=None):
    return get_scraper_class(venue.scraper)(venue, client=client)
