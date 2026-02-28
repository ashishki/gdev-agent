"""Redis-backed pending approval store."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.schemas import PendingDecision

LOGGER = logging.getLogger(__name__)


class RedisApprovalStore:
    """Stores pending decisions in Redis with TTL."""

    def __init__(self, redis_client: Any, ttl_seconds: int) -> None:
        self.redis = redis_client
        self.ttl_seconds = ttl_seconds

    def put_pending(self, decision: PendingDecision) -> None:
        """Store pending decision with expiration TTL."""
        key = f"pending:{decision.pending_id}"
        payload = decision.model_dump(mode="json")
        self.redis.set(key, PendingDecision(**payload).model_dump_json(), ex=self.ttl_seconds)

    def pop_pending(self, pending_id: str) -> PendingDecision | None:
        """Atomically fetch and delete pending decision."""
        key = f"pending:{pending_id}"
        raw = self.redis.execute_command("GETDEL", key)
        if raw is None:
            return None
        text = raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)
        decision = PendingDecision.model_validate_json(text)
        if decision.expires_at < datetime.now(UTC):
            LOGGER.info(
                "pending expired",
                extra={"event": "pending_expired", "context": {"pending_id": pending_id}},
            )
            return None
        return decision

    def get_pending(self, pending_id: str) -> PendingDecision | None:
        """Read pending decision without deleting it."""
        key = f"pending:{pending_id}"
        raw = self.redis.get(key)
        if raw is None:
            return None
        text = raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)
        decision = PendingDecision.model_validate_json(text)
        if decision.expires_at < datetime.now(UTC):
            self.redis.delete(key)
            LOGGER.info(
                "pending expired",
                extra={"event": "pending_expired", "context": {"pending_id": pending_id}},
            )
            return None
        return decision
