"""Simple in-memory store with optional SQLite event logging."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from app.schemas import PendingDecision


class EventStore:
    """Stores pending approvals and optionally writes events to SQLite."""

    def __init__(self, sqlite_path: str | None = None) -> None:
        self._pending: dict[str, PendingDecision] = {}
        self._lock = Lock()
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

    def put_pending(self, pending: PendingDecision) -> None:
        """Store a pending approval object."""
        with self._lock:
            self._pending[pending.pending_id] = pending
        self.log_event("pending_created", pending.model_dump())

    def pop_pending(self, pending_id: str) -> PendingDecision | None:
        """Fetch and remove a pending approval by id."""
        with self._lock:
            pending = self._pending.pop(pending_id, None)
        if pending and pending.expires_at <= datetime.now(UTC):
            self.log_event("pending_expired", {"pending_id": pending_id})
            return None
        if pending:
            self.log_event("pending_resolved", {"pending_id": pending_id})
        return pending

    def get_pending(self, pending_id: str) -> PendingDecision | None:
        """Get a pending approval object by id."""
        with self._lock:
            return self._pending.get(pending_id)

    def log_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Persist an event to SQLite when configured."""
        if not self._conn:
            return
        self._conn.execute(
            "INSERT INTO event_log(ts, event_type, payload) VALUES (?, ?, ?)",
            (datetime.now(UTC).isoformat(), event_type, json.dumps(payload, ensure_ascii=False)),
        )
        self._conn.commit()
