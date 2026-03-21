"""Event store with optional Postgres-backed pipeline persistence."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import _set_tenant_ctx
from app.schemas import (
    AuditLogEntry,
    ClassificationResult,
    ExtractedFields,
    ProposedAction,
    WebhookRequest,
)
from app.utils import run_blocking

UTC = timezone.utc


class EventStore:
    """Persists events to SQLite and pipeline runs to Postgres when configured."""

    def __init__(
        self,
        sqlite_path: str | None = None,
        db_session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._conn: sqlite3.Connection | None = None
        self._db_session_factory = db_session_factory
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
            (
                datetime.now(UTC).isoformat(),
                event_type,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        self._conn.commit()

    def persist_pipeline_run(
        self,
        payload: WebhookRequest,
        classification: ClassificationResult,
        extracted: ExtractedFields,
        action: ProposedAction,
        audit_entry: AuditLogEntry,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> str | None:
        """Persist ticket + classification + extracted + action + audit in one transaction."""
        if self._db_session_factory is None:
            return None
        return run_blocking(
            self._persist_pipeline_run_async(
                payload,
                classification,
                extracted,
                action,
                audit_entry,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        )

    async def _persist_pipeline_run_async(
        self,
        payload: WebhookRequest,
        classification: ClassificationResult,
        extracted: ExtractedFields,
        action: ProposedAction,
        audit_entry: AuditLogEntry,
        *,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> str:
        if payload.tenant_id is None or audit_entry.tenant_id is None:
            raise ValueError("tenant_id is required for Postgres EventStore writes")
        if self._db_session_factory is None:
            raise ValueError("db_session_factory is required for Postgres EventStore writes")

        payload_tenant_id = UUID(str(payload.tenant_id))
        audit_tenant_id = UUID(str(audit_entry.tenant_id))
        if payload_tenant_id != audit_tenant_id:
            raise ValueError("tenant_id mismatch between webhook payload and audit log entry")

        user_id_hash = hashlib.sha256((payload.user_id or "").encode()).hexdigest()

        async with self._db_session_factory() as session:
            async with session.begin():
                await _set_tenant_ctx(session, str(payload_tenant_id))
                ticket_row = await session.execute(
                    text(
                        """
                        INSERT INTO tickets (
                            tenant_id, message_id, user_id_hash, raw_text, platform, game_title
                        )
                        VALUES (
                            :tenant_id, :message_id, :user_id_hash, :raw_text, :platform, :game_title
                        )
                        RETURNING ticket_id
                        """
                    ),
                    {
                        "tenant_id": str(payload_tenant_id),
                        "message_id": payload.message_id,
                        "user_id_hash": user_id_hash,
                        "raw_text": payload.text,
                        "platform": extracted.platform,
                        "game_title": extracted.game_title,
                    },
                )
                ticket_id = ticket_row.scalar_one()

                await session.execute(
                    text(
                        """
                        INSERT INTO ticket_classifications (
                            ticket_id, tenant_id, category, urgency, confidence
                        )
                        VALUES (
                            :ticket_id, :tenant_id, :category, :urgency, :confidence
                        )
                        """
                    ),
                    {
                        "ticket_id": str(ticket_id),
                        "tenant_id": str(payload_tenant_id),
                        "category": classification.category,
                        "urgency": classification.urgency,
                        "confidence": classification.confidence,
                    },
                )

                await session.execute(
                    text(
                        """
                        INSERT INTO ticket_extracted_fields (
                            ticket_id, tenant_id, fields
                        )
                        VALUES (
                            :ticket_id, :tenant_id, CAST(:fields AS jsonb)
                        )
                        """
                    ),
                    {
                        "ticket_id": str(ticket_id),
                        "tenant_id": str(payload_tenant_id),
                        "fields": json.dumps(extracted.model_dump(mode="json"), ensure_ascii=False),
                    },
                )

                await session.execute(
                    text(
                        """
                        INSERT INTO proposed_actions (
                            ticket_id, tenant_id, action_tool, payload, risky
                        )
                        VALUES (
                            :ticket_id, :tenant_id, :action_tool, CAST(:payload AS jsonb), :risky
                        )
                        """
                    ),
                    {
                        "ticket_id": str(ticket_id),
                        "tenant_id": str(payload_tenant_id),
                        "action_tool": action.tool,
                        "payload": json.dumps(action.payload, ensure_ascii=False),
                        "risky": action.risky,
                    },
                )

                await session.execute(
                    text(
                        """
                        INSERT INTO audit_log (
                            tenant_id,
                            request_id,
                            message_id,
                            user_id_hash,
                            category,
                            urgency,
                            confidence,
                            action_tool,
                            status,
                            approved_by,
                            ticket_id,
                            latency_ms,
                            input_tokens,
                            output_tokens,
                            cost_usd
                        )
                        VALUES (
                            :tenant_id,
                            :request_id,
                            :message_id,
                            :user_id_hash,
                            :category,
                            :urgency,
                            :confidence,
                            :action_tool,
                            :status,
                            :approved_by,
                            :ticket_id,
                            :latency_ms,
                            :input_tokens,
                            :output_tokens,
                            :cost_usd
                        )
                        """
                    ),
                    {
                        "tenant_id": str(payload_tenant_id),
                        "request_id": audit_entry.request_id,
                        "message_id": audit_entry.message_id,
                        "user_id_hash": user_id_hash,
                        "category": audit_entry.category,
                        "urgency": audit_entry.urgency,
                        "confidence": audit_entry.confidence,
                        "action_tool": audit_entry.action,
                        "status": audit_entry.status,
                        "approved_by": audit_entry.approved_by,
                        "ticket_id": str(ticket_id),
                        "latency_ms": audit_entry.latency_ms,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cost_usd": audit_entry.cost_usd,
                    },
                )

        return str(ticket_id)
