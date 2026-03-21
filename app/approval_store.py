"""Redis-backed pending approval store."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import _set_tenant_ctx
from app.metrics import APPROVAL_QUEUE_DEPTH
from app.schemas import PendingDecision
from app.utils import run_blocking

UTC = timezone.utc

LOGGER = logging.getLogger(__name__)


class RedisApprovalStore:
    """Stores pending decisions in Redis with TTL."""

    def __init__(
        self,
        redis_client: Any,
        ttl_seconds: int,
        db_session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.redis = redis_client
        self.ttl_seconds = ttl_seconds
        self._db_session_factory = db_session_factory

    def put_pending(self, decision: PendingDecision) -> None:
        """Store pending decision with expiration TTL."""
        key = self._key(str(decision.tenant_id), str(decision.pending_id))
        payload = decision.model_dump(mode="json")
        self.redis.set(
            key,
            PendingDecision(**payload).model_dump_json(),
            ex=self.ttl_seconds,
        )
        if self._db_session_factory is not None:
            try:
                run_blocking(self._persist_pending_async(decision))
            except Exception:
                self.redis.delete(key)
                raise
        APPROVAL_QUEUE_DEPTH.labels(tenant_hash=_sha256_short(decision.tenant_id)).inc()

    def pop_pending(self, tenant_id: str, pending_id: str) -> PendingDecision | None:
        """Atomically fetch and delete pending decision."""
        key = self._key(tenant_id, pending_id)
        raw = self.redis.execute_command("GETDEL", key)
        if raw is None:
            return None
        text = raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)
        decision = PendingDecision.model_validate_json(text)
        APPROVAL_QUEUE_DEPTH.labels(tenant_hash=_sha256_short(decision.tenant_id)).dec()
        if decision.expires_at < datetime.now(UTC):
            LOGGER.info(
                "pending expired",
                extra={
                    "event": "pending_expired",
                    "context": {"pending_id": pending_id},
                },
            )
            return None
        return decision

    def get_pending(self, tenant_id: str, pending_id: str) -> PendingDecision | None:
        """Read pending decision without deleting it."""
        key = self._key(tenant_id, pending_id)
        raw = self.redis.get(key)
        if raw is None:
            return None
        text = raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)
        decision = PendingDecision.model_validate_json(text)
        if decision.expires_at < datetime.now(UTC):
            self.redis.delete(key)
            APPROVAL_QUEUE_DEPTH.labels(tenant_hash=_sha256_short(decision.tenant_id)).dec()
            LOGGER.info(
                "pending expired",
                extra={
                    "event": "pending_expired",
                    "context": {"pending_id": pending_id},
                },
            )
            return None
        return decision

    @staticmethod
    def _key(tenant_id: str, pending_id: str) -> str:
        return f"{tenant_id}:pending:{pending_id}"

    async def _persist_pending_async(self, decision: PendingDecision) -> None:
        if self._db_session_factory is None:
            return
        tenant_uuid = UUID(str(decision.tenant_id))
        pending_uuid = UUID(str(decision.pending_id))
        async with self._db_session_factory() as session:
            async with session.begin():
                await _set_tenant_ctx(session, str(tenant_uuid))
                await session.execute(
                    text(
                        """
                        INSERT INTO pending_decisions (
                            pending_id, tenant_id, payload, expires_at, status
                        )
                        VALUES (
                            :pending_id, :tenant_id, CAST(:payload AS jsonb), :expires_at, 'pending'
                        )
                        """
                    ),
                    {
                        "pending_id": str(pending_uuid),
                        "tenant_id": str(tenant_uuid),
                        "payload": PendingDecision(
                            **decision.model_dump(mode="json")
                        ).model_dump_json(),
                        "expires_at": decision.expires_at,
                    },
                )


def _sha256_short(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
