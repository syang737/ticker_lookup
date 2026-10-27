"""SQLite cache of OpenFIGI answers.

The same identifiers come back request after request, and the CUSIP-to-ticker
mapping rarely changes. Misses expire sooner than hits, since a new listing
can turn a not-found into a match.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

HIT_TTL = 7 * 86400
MISS_TTL = 86400


class FigiCache:
    def __init__(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._db:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS figi ("
                " kind TEXT, value TEXT, rows TEXT, fetched REAL,"
                " PRIMARY KEY (kind, value))"
            )

    def get_many(self, keys: list[tuple[str, str]]) -> dict[tuple[str, str], list[dict]]:
        now = time.time()
        found = {}
        with self._lock:
            for value, kind in keys:
                row = self._db.execute(
                    "SELECT rows, fetched FROM figi WHERE kind = ? AND value = ?", (kind, value)
                ).fetchone()
                if row is None:
                    continue
                rows = json.loads(row[0])
                if now - row[1] < (HIT_TTL if rows else MISS_TTL):
                    found[(value, kind)] = rows
        return found

    def put_many(self, results: dict[tuple[str, str], list[dict]]) -> None:
        now = time.time()
        with self._lock, self._db:
            self._db.executemany(
                "INSERT OR REPLACE INTO figi VALUES (?, ?, ?, ?)",
                [(kind, value, json.dumps(rows), now) for (value, kind), rows in results.items()],
            )
