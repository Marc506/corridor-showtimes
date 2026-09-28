"""SQLite persistence. Success replaces a venue's future rows; failure only marks status stale."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import Screening, VenueStatus
from .normalize import now_utc_iso, today_local

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "showtimes.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS screenings (
  id TEXT PRIMARY KEY, venue_id TEXT NOT NULL, title TEXT NOT NULL,
  start TEXT NOT NULL, "end" TEXT, day TEXT NOT NULL,
  director TEXT, year INTEGER, runtime_min INTEGER, format TEXT, language TEXT,
  series TEXT, screen TEXT, note TEXT, detail_url TEXT, ticket_url TEXT,
  source TEXT NOT NULL, scraped_at TEXT NOT NULL,
  first_seen TEXT NOT NULL, last_seen TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_screenings_day ON screenings(day);
CREATE INDEX IF NOT EXISTS ix_screenings_venue_day ON screenings(venue_id, day);
CREATE TABLE IF NOT EXISTS venue_status (
  venue_id TEXT PRIMARY KEY, status TEXT, fetched_at TEXT, count INTEGER,
  horizon_end TEXT, error TEXT, source TEXT, updated_at TEXT,
  primary_failed_at TEXT
);
"""

SCREENING_COLS = ["id", "venue_id", "title", "start", "end", "day", "director", "year",
                  "runtime_min", "format", "language", "series", "screen", "note", "detail_url",
                  "ticket_url", "source", "scraped_at"]


class Store:
    def __init__(self, path: Path = DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        if "language" not in {r[1] for r in self.conn.execute("PRAGMA table_info(screenings)")}:
            self.conn.execute("ALTER TABLE screenings ADD COLUMN language TEXT")
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(venue_status)")}
        if "primary_failed_at" not in cols:          # migrate databases created before this column existed
            self.conn.execute("ALTER TABLE venue_status ADD COLUMN primary_failed_at TEXT")

    def close(self) -> None:
        self.conn.close()

    # --- reads ----------------------------------------------------------------------
    def get_status(self, venue_id: str) -> VenueStatus | None:
        row = self.conn.execute("SELECT * FROM venue_status WHERE venue_id=?", (venue_id,)).fetchone()
        if not row:
            return None
        return VenueStatus(row["venue_id"], row["status"], row["fetched_at"], row["count"] or 0,
                           row["horizon_end"], row["error"], row["source"] or "primary")

    def all_statuses(self) -> dict[str, VenueStatus]:
        ids = [r[0] for r in self.conn.execute("SELECT venue_id FROM venue_status")]
        return {i: self.get_status(i) for i in ids}

    def screenings_since(self, day: str) -> list[dict]:
        rows = self.conn.execute(
            'SELECT * FROM screenings WHERE day >= ? ORDER BY start, venue_id, title', (day,))
        return [dict(r) for r in rows]

    def title_years(self) -> list[tuple]:
        """(title, year, director) for recent screenings that have a year — cross-venue hints."""
        return self.conn.execute(
            "SELECT DISTINCT title, year, director FROM screenings WHERE year IS NOT NULL AND day >= ?",
            ((today_local()).replace(day=1).isoformat(),)).fetchall()

    def _future_summary(self, venue_id: str) -> tuple[int, str | None]:
        row = self.conn.execute(
            "SELECT COUNT(*), MAX(day) FROM screenings WHERE venue_id=? AND day>=?",
            (venue_id, today_local().isoformat())).fetchone()
        return row[0], row[1]

    # --- writes ---------------------------------------------------------------------
    def apply_success(self, venue_id: str, screenings: list[Screening], status: VenueStatus,
                      primary_result: str = "ok") -> VenueStatus:
        now = now_utc_iso()
        today = today_local().isoformat()
        with self.conn:
            first_seen = dict(self.conn.execute(
                "SELECT id, first_seen FROM screenings WHERE venue_id=?", (venue_id,)).fetchall())
            self.conn.execute("DELETE FROM screenings WHERE venue_id=? AND day>=?", (venue_id, today))
            placeholders = ",".join("?" * (len(SCREENING_COLS) + 2))
            cols = ",".join(f'"{c}"' for c in SCREENING_COLS + ["first_seen", "last_seen"])
            self.conn.executemany(
                f"INSERT OR REPLACE INTO screenings ({cols}) VALUES ({placeholders})",
                [[getattr(s, c) for c in SCREENING_COLS] + [first_seen.get(s.id, now), now]
                 for s in screenings])
            count, horizon = self._future_summary(venue_id)
            status.count, status.horizon_end = count, horizon
            self._write_status(status, now, primary_result)
        return status

    def apply_failure(self, venue_id: str, status: VenueStatus, primary_result: str = "failed") -> VenueStatus:
        """Keep old rows; status becomes 'stale' if we still have data, else 'failed'."""
        prev = self.get_status(venue_id)
        count, horizon = self._future_summary(venue_id)
        status.fetched_at = prev.fetched_at if prev else None
        status.count, status.horizon_end = count, horizon
        if status.status != "disabled":
            status.status = "stale" if count or status.fetched_at else "failed"
        with self.conn:
            self._write_status(status, now_utc_iso(), primary_result)
        return status

    # --- primary-source cooldown ------------------------------------------------------
    def primary_failed_at(self, venue_id: str) -> str | None:
        row = self.conn.execute("SELECT primary_failed_at FROM venue_status WHERE venue_id=?",
                                (venue_id,)).fetchone()
        return row[0] if row else None

    def _write_status(self, s: VenueStatus, now: str, primary_result: str = "ok") -> None:
        """primary_result: 'ok' clears primary_failed_at, 'failed' stamps it, 'skipped' keeps it."""
        pfa = {"ok": None, "failed": now}.get(primary_result, self.primary_failed_at(s.venue_id))
        self.conn.execute(
            'INSERT OR REPLACE INTO venue_status (venue_id, status, fetched_at, count, horizon_end, error, '
            'source, updated_at, primary_failed_at) VALUES (?,?,?,?,?,?,?,?,?)',
            (s.venue_id, s.status, s.fetched_at, s.count, s.horizon_end, s.error, s.source, now, pfa))
