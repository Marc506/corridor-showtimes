"""Adapter registry: reusable data sources configured by parameters, not code.

    @register_adapter("filmbot")
    class FilmbotAdapter(BaseScraper):
        PARAMS = {"base_url": str}            # required keys of venues.yaml `source:` (checked on load)
        OPTIONAL_PARAMS = {"categories": list}
        DETECT_ORDER = 10                     # the add-venue wizard asks adapters in this order
        @classmethod
        def detect(cls, probe) -> Candidate | None: ...

A venue selects one with `source: {adapter: filmbot, base_url: …}`; `adapter: custom` keeps using the
hand-written modules in scraper/sources/ (see scraper.registry.build_scraper).
"""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field

ADAPTERS: dict[str, type] = {}


@dataclass
class Candidate:
    """What an adapter's detect() found on a site: enough to write a venues.yaml `source:`."""

    adapter: str
    params: dict
    evidence: list[str] = field(default_factory=list)
    order: int = 100                       # the adapter's DETECT_ORDER; lower wins ties

    @property
    def source(self) -> dict:
        return {"adapter": self.adapter, **self.params}


def module_name(adapter: str) -> str:
    return adapter.replace("-", "_")


def register_adapter(name: str):
    def deco(cls):
        ADAPTERS[name] = cls
        cls.adapter_name = name
        cls.scraper_name = name
        cls.enforce_budget = getattr(cls, "enforce_budget", True)
        return cls
    return deco


def get_adapter_class(name: str) -> type:
    if name not in ADAPTERS:
        try:
            importlib.import_module(f"{__name__}.{module_name(name)}")
        except ModuleNotFoundError as e:
            if e.name != f"{__name__}.{module_name(name)}":
                raise
            raise KeyError(name) from None
    if name not in ADAPTERS:
        raise KeyError(name)
    return ADAPTERS[name]


def load_all() -> dict[str, type]:
    for info in pkgutil.iter_modules(__path__):
        importlib.import_module(f"{__name__}.{info.name}")
    return ADAPTERS


def known_adapters() -> list[str]:
    return sorted(load_all())


def detectable_adapters() -> list[type]:
    """Adapters that implement detect(), in DETECT_ORDER."""
    return sorted((c for c in load_all().values() if "detect" in c.__dict__),
                  key=lambda c: (c.DETECT_ORDER, c.adapter_name))
