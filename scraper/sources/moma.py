"""MoMA — the film calendar as a JSON file dropped into a local folder (SOURCES.md §8).

    source: {adapter: custom, module: moma}
    inbox: inbox/moma            # venue-level: folder (relative to the project) the files arrive in

moma.org answers this machine's programs with Cloudflare's challenge, which is never worked around. The owner
runs a low-rate reader of MoMA's calendar elsewhere and drops its output here (`moma_films_YYYY-MM-DD.json`):
one record per screening —

    {"event_id": 11729, "url": "https://www.moma.org/calendar/events/11729", "start": "2026-11-03T19:30:00-05:00",
     "program_title": "The Trial (ПРОЦЕСС). 2018. Written and directed by Sergei Loznitsa",
     "films": [{"title": "The Trial (ПРОЦЕСС)", "year": 2018, "directors": ["Sergei Loznitsa"], "runtime_min": 129}],
     "runtime_min": 129, "end_estimate": "…", "venue": "MoMA, Floor T2 · Theater 2", "series": "Sergei Loznitsa",
     "note": null, "kind": "Film", "ticket_url": "https://membership.moma.org/tickets/film/select?…"}

Every update reads the newest file and deletes the older ones (only one is kept). A file older than STALE_DAYS
fails the run, so the venue shows as stale (its last data stays) until a new file arrives.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..base import ROOT, BaseScraper, ScrapeError
from ..models import RawPage, Screening
from ..normalize import clean_text, iso, make_id, parse_iso
from ..registry import register

STALE_DAYS = 10
PATTERN = "moma_films*.json"


def title_of(rec: dict) -> str | None:
    """One film: its title; two: 'A + B'; more: 'A + B + N more'; none listed (a programme): MoMA's name."""
    names = [clean_text(f.get("title")) for f in rec.get("films") or [] if clean_text(f.get("title"))]
    if len(names) == 1:
        return names[0]
    if len(names) in (2, 3):
        return " + ".join(names)
    if names:
        return f"{names[0]} + {names[1]} + {len(names) - 2} more"
    return clean_text(rec.get("program_title"))


def newest(inbox: Path) -> Path | None:
    """The newest file in the inbox; the older ones are deleted so they don't pile up."""
    files = sorted(inbox.glob(PATTERN), key=lambda p: (p.stat().st_mtime, p.name))
    for old in files[:-1]:
        old.unlink(missing_ok=True)
    return files[-1] if files else None


@register("moma")
class MomaScraper(BaseScraper):
    def inbox(self) -> Path:
        return ROOT / (self.venue.extra.get("inbox") or "inbox/moma")

    def fetch(self) -> list[RawPage]:
        inbox = self.inbox()
        inbox.mkdir(parents=True, exist_ok=True)
        f = newest(inbox)
        if f is None:
            raise ScrapeError(f"no MoMA file in {inbox.relative_to(ROOT)}/ yet")
        stamp = datetime.fromtimestamp(f.stat().st_mtime, timezone.utc)
        age = (datetime.now(timezone.utc) - stamp).days
        if age > STALE_DAYS:
            raise ScrapeError(f"newest MoMA file {f.name} is {age} days old (a new one is due)")
        return [RawPage(url=f"file://{f}", body=f.read_text(encoding="utf-8"), ext="json",
                        fetched_at=stamp.strftime("%Y-%m-%dT%H:%M:%SZ"))]

    def parse(self, pages: list[RawPage]) -> list[Screening]:
        out = []
        for page in pages:
            for rec in json.loads(page.body):
                title = title_of(rec)
                if not title or not rec.get("start"):
                    continue
                start = parse_iso(rec["start"], self.tz)
                films = rec.get("films") or []
                directors = list(dict.fromkeys(d for f in films for d in f.get("directors") or [] if d))
                end = parse_iso(rec["end_estimate"], self.tz) if rec.get("end_estimate") else None
                venue = clean_text(rec.get("venue")) or ""
                kind = clean_text(rec.get("kind")) or ""
                notes = [clean_text(rec.get("note"))]
                if kind.lower().startswith("film, "):                 # "Film, for kids"
                    notes.append(kind[6:].strip().capitalize())
                start_s = iso(start, self.tz)
                out.append(Screening(
                    id=make_id(self.venue.id, start_s, title), venue_id=self.venue.id, title=title,
                    start=start_s, day=start.date().isoformat(), end=iso(end, self.tz) if end and end > start else None,
                    director=(", ".join(directors[:3]) + (", …" if len(directors) > 3 else "")) or None,
                    year=films[0].get("year") if len(films) == 1 else None,
                    runtime_min=rec.get("runtime_min") or None, series=clean_text(rec.get("series")),
                    screen=venue.split("·")[-1].strip() or None,
                    note="; ".join(n for n in notes if n) or None,
                    detail_url=rec.get("url"), ticket_url=rec.get("ticket_url"), scraped_at=page.fetched_at))
        return out

