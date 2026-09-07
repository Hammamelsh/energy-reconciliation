"""Disk-backed aggregation for duplicate detection and per-household observations.

Holding a million rows in Python objects to find duplicates costs hundreds of
megabytes. Streaming them into SQLite instead keeps resident memory flat at a few
megabytes regardless of member size, and the answers stay exact rather than
approximate. SQLite is in the standard library, so this adds no dependency.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

BATCH = 20_000

SCHEMA = """
CREATE TABLE rec (
    n       INTEGER PRIMARY KEY,   -- record number, 1-based, header excluded
    lclid   TEXT NOT NULL,         -- raw field, untrimmed
    tariff  TEXT NOT NULL,         -- raw field, untrimmed
    ts      TEXT NOT NULL,         -- raw timestamp text, never converted
    val     TEXT NOT NULL,         -- raw consumption text, untrimmed
    normval TEXT NOT NULL,         -- normalised comparison key for 'same meaning'
    numval  REAL                   -- ordering key for finite values only; NULL otherwise
);
"""

INDEXES = """
CREATE INDEX idx_key   ON rec (lclid, ts);
CREATE INDEX idx_exact ON rec (lclid, tariff, ts, val);
CREATE INDEX idx_num   ON rec (numval) WHERE numval IS NOT NULL;
"""


@dataclass(frozen=True, slots=True)
class HouseholdObservation:
    """What was seen for one household **in this member only**.

    Deliberately not called a 'complete run': Phase F proved households span member
    boundaries, so rows ending here do not mean the household's data ends here.
    """

    lclid: str
    rows: int
    first_ts_in_member: str
    last_ts_in_member: str
    backwards_steps: int
    repeated_steps: int


class RecordStore:
    """Accumulates records on disk, then answers duplicate and grouping questions."""

    def __init__(self, db_path: Path) -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;")
        self._conn.executescript(SCHEMA)
        self._buffer: list[tuple[int, str, str, str, str, str, float | None]] = []

    def add(
        self,
        n: int,
        lclid: str,
        tariff: str,
        ts: str,
        val: str,
        normval: str,
        numval: float | None = None,
    ) -> None:
        """Store one record. ``numval`` is an ordering key, set only for finite values."""
        self._buffer.append((n, lclid, tariff, ts, val, normval, numval))
        if len(self._buffer) >= BATCH:
            self.flush()

    def flush(self) -> None:
        if self._buffer:
            self._conn.executemany(
                "INSERT INTO rec (n, lclid, tariff, ts, val, normval, numval) "
                "VALUES (?,?,?,?,?,?,?)",
                self._buffer,
            )
            self._buffer.clear()

    def finalise(self) -> None:
        self.flush()
        self._conn.executescript(INDEXES)
        self._conn.commit()

    def _one(self, sql: str) -> int:
        row = self._conn.execute(sql).fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    # -- duplicates -------------------------------------------------------------

    def exact_duplicate_stats(self) -> dict[str, int]:
        """Exact source-row equality: all four raw fields identical, whitespace included."""
        groups = """
            SELECT COUNT(*) AS c FROM rec
            GROUP BY lclid, tariff, ts, val HAVING c > 1
        """
        return {
            "groups": self._one(f"SELECT COUNT(*) FROM ({groups})"),
            "extra_rows": self._one(f"SELECT COALESCE(SUM(c - 1), 0) FROM ({groups})"),
            "rows_involved": self._one(f"SELECT COALESCE(SUM(c), 0) FROM ({groups})"),
        }

    def key_collision_stats(self) -> dict[str, int]:
        """Candidate key = (household, raw timestamp text). Physical meaning unresolved."""
        groups = """
            SELECT COUNT(*) AS c, COUNT(DISTINCT normval || '\\x1f' || tariff) AS d
            FROM rec GROUP BY lclid, ts HAVING c > 1
        """
        return {
            "colliding_keys": self._one(f"SELECT COUNT(*) FROM ({groups})"),
            "extra_rows": self._one(f"SELECT COALESCE(SUM(c - 1), 0) FROM ({groups})"),
            "rows_involved": self._one(f"SELECT COALESCE(SUM(c), 0) FROM ({groups})"),
            "conflicting_groups": self._one(
                f"SELECT COUNT(*) FROM ({groups}) WHERE d > 1"
            ),
        }

    def conflicting_examples(self, limit: int = 5) -> list[dict[str, object]]:
        sql = """
            SELECT lclid, ts, COUNT(*) AS c,
                   COUNT(DISTINCT normval || '\\x1f' || tariff) AS d,
                   MIN(n), MAX(n)
            FROM rec GROUP BY lclid, ts HAVING c > 1 AND d > 1
            LIMIT ?
        """
        return [
            {
                "lclid": r[0],
                "timestamp_text": r[1],
                "rows_in_group": r[2],
                "distinct_meanings": r[3],
                "first_record_no": r[4],
                "last_record_no": r[5],
            }
            for r in self._conn.execute(sql, (limit,))
        ]

    def duplicate_key_examples(self, limit: int = 5) -> list[dict[str, object]]:
        sql = """
            SELECT lclid, ts, COUNT(*) AS c, MIN(n), MAX(n)
            FROM rec GROUP BY lclid, ts HAVING c > 1 LIMIT ?
        """
        return [
            {
                "lclid": r[0],
                "timestamp_text": r[1],
                "rows_in_group": r[2],
                "first_record_no": r[3],
                "last_record_no": r[4],
            }
            for r in self._conn.execute(sql, (limit,))
        ]

    # -- households -------------------------------------------------------------

    def distinct_households(self) -> int:
        return self._one("SELECT COUNT(DISTINCT lclid) FROM rec")

    def tariff_values(self) -> dict[str, int]:
        return {
            r[0]: r[1]
            for r in self._conn.execute(
                "SELECT tariff, COUNT(*) FROM rec GROUP BY tariff ORDER BY tariff"
            )
        }

    def households(self) -> Iterator[HouseholdObservation]:
        """Per household, in this member only. Text comparison is safe because the
        timestamp format is fixed-width and lexicographically ordered."""
        sql = """
            WITH stepped AS (
                SELECT lclid, ts, LAG(ts) OVER (PARTITION BY lclid ORDER BY n) AS prev
                FROM rec
            )
            SELECT lclid,
                   COUNT(*),
                   MIN(ts),
                   MAX(ts),
                   SUM(CASE WHEN prev IS NOT NULL AND ts <  prev THEN 1 ELSE 0 END),
                   SUM(CASE WHEN prev IS NOT NULL AND ts =  prev THEN 1 ELSE 0 END)
            FROM stepped GROUP BY lclid ORDER BY lclid
        """
        for r in self._conn.execute(sql):
            yield HouseholdObservation(r[0], r[1], r[2], r[3], int(r[4]), int(r[5]))

    # -- consumption distribution ----------------------------------------------

    def finite_count(self) -> int:
        """Rows holding an orderable numeric value. Cross-checks the streaming count."""
        return self._one("SELECT COUNT(*) FROM rec WHERE numval IS NOT NULL")

    def value_at_rank(self, rank: int) -> tuple[str, int] | None:
        """Return ``(raw value text, record number)`` at a 1-based ascending rank.

        Selection is by nearest rank, so the value returned is an **actually observed
        value** and never an interpolation between two observations.
        """
        row = self._conn.execute(
            "SELECT val, n FROM rec WHERE numval IS NOT NULL "
            "ORDER BY numval, n LIMIT 1 OFFSET ?",
            (rank - 1,),
        ).fetchone()
        return (row[0], row[1]) if row else None

    def extreme_values(self, limit: int, *, largest: bool) -> list[dict[str, object]]:
        """The ``limit`` smallest or largest observed values, with source references."""
        order = "DESC" if largest else "ASC"
        sql = (
            "SELECT val, n, lclid, ts FROM rec WHERE numval IS NOT NULL "
            f"ORDER BY numval {order}, n LIMIT ?"
        )
        return [
            {
                "value_text": r[0],
                "record_no": r[1],
                "lclid": r[2],
                "timestamp_text": r[3],
            }
            for r in self._conn.execute(sql, (limit,))
        ]

    def timestamp_range(self) -> tuple[str | None, str | None]:
        row = self._conn.execute("SELECT MIN(ts), MAX(ts) FROM rec").fetchone()
        return (row[0], row[1]) if row else (None, None)

    def close(self) -> None:
        self._conn.close()


@contextmanager
def record_store(db_path: Path) -> Iterator[RecordStore]:
    store = RecordStore(db_path)
    try:
        yield store
    finally:
        store.close()
