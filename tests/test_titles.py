"""Every title problem seen in a real listing, and what must stay (tests/fixtures/titles.yaml)."""
import pytest
import yaml

from scraper.models import Screening
from scraper.registry import load_venues
from scraper.titles import audit, tidy
from tests.conftest import FIXTURES

GROUPS = yaml.safe_load((FIXTURES / "titles.yaml").read_text())["groups"]
VENUES = {v.id: v for v in load_venues()}


def _cases():
    for g in GROUPS:
        for i, row in enumerate(g["rows"]):
            yield pytest.param(g, i, id=f"{g['venue']}: {row['title']}")


@pytest.mark.parametrize("group,i", list(_cases()))
def test_title_table(group, i):
    rows = [Screening(id=str(n), venue_id=group["venue"], title=r["title"], start="2026-11-14T19:00:00-05:00",
                      day="2026-11-14", director=r.get("director"), series=r.get("series"), screen=r.get("screen"))
            for n, r in enumerate(group["rows"])]
    tidy(rows, VENUES[group["venue"]])
    case, s = group["rows"][i], rows[i]
    if case.get("keep"):
        assert (s.title, s.note) == (case["title"], None)
        return
    for field, want in case["expect"].items():
        assert getattr(s, field) == want, field


def test_audit_flags_what_still_looks_like_a_label():
    rows = [("v", "Zoe Beloff presents Life Forgotten"), ("v", "Railway Sleepers preceded by A Child"),
            ("v", "Seminar: One"), ("v", "Seminar: Two"), ("v", "The General")]
    whys = {(t, w) for _, t, w in audit(rows)}
    assert ("Zoe Beloff presents Life Forgotten", "presenter") in whys
    assert ("Railway Sleepers preceded by A Child", "support short") in whys
    assert ("Seminar: One", "shared prefix") in whys and not any(t == "The General" for t, _ in whys)
