"""Redis-backed dedup cache for idempotent webhook responses."""

from __future__ import annotations

from typing import Any


class DedupCache:
    """Simple message_id response cache."""

    def __init__(self, redis_client: Any, ttl_seconds: int = 86400) -> None:
        self.redis = redis_client
        self.ttl_seconds = ttl_seconds

    def check(self, tenant_id: str, message_id: str) -> str | None:
        """Return cached response JSON when present."""
        raw = self.redis.get(f"dedup:{tenant_id}:{message_id}")
        if raw is None:
            return None
        return raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)

    def set(self, tenant_id: str, message_id: str, response_json: str) -> None:
        """Cache response JSON under dedup key."""
        self.redis.set(
            f"dedup:{tenant_id}:{message_id}", response_json, ex=self.ttl_seconds
        )
