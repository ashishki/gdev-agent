"""SQLite-backed event log store."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any


class EventStore:
    """Persists events to SQLite when configured."""

    def __init__(self, sqlite_path: str | None = None) -> None:
        self._conn: sqlite3.Connection | None = None
        if sqlite_path:
            self._conn = sqlite3.connect(sqlite_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS event_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            self._conn.commit()

    def log_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Persist an event to SQLite when configured."""
        if not self._conn:
            return
        self._conn.execute(
            "INSERT INTO event_log(ts, event_type, payload) VALUES (?, ?, ?)",
            (datetime.now(UTC).isoformat(), event_type, json.dumps(payload, ensure_ascii=False)),
        )
        self._conn.commit()
