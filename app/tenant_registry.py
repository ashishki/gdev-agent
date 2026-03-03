"""Tenant configuration registry backed by Redis cache and Postgres."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class TenantNotFoundError(Exception):
    """Raised when a tenant does not exist or is inactive."""


@dataclass
class TenantConfig:
    tenant_id: UUID
    slug: str
    daily_budget_usd: Decimal
    approval_ttl_s: int
    auto_approve_threshold: float
    approval_categories: list[str]
    url_allowlist: list[str]
    is_active: bool


class TenantRegistry:
    """Loads tenant configuration from cache or Postgres."""

    def __init__(
        self,
        redis_client,
        db_session_factory: async_sessionmaker[AsyncSession],
        ttl_seconds: int = 300,
    ) -> None:
        self._redis = redis_client
        self._db_session_factory = db_session_factory
        self._ttl_seconds = ttl_seconds

    async def get_tenant_config(self, tenant_id: UUID) -> TenantConfig:
        cache_key = self._cache_key(tenant_id)
        cached = self._redis.get(cache_key)
        if cached:
            if isinstance(cached, bytes):
                cached = cached.decode("utf-8")
            payload = json.loads(cached)
            return TenantConfig(
                tenant_id=UUID(payload["tenant_id"]),
                slug=payload["slug"],
                daily_budget_usd=Decimal(payload["daily_budget_usd"]),
                approval_ttl_s=payload["approval_ttl_s"],
                auto_approve_threshold=payload["auto_approve_threshold"],
                approval_categories=list(payload["approval_categories"]),
                url_allowlist=list(payload["url_allowlist"]),
                is_active=payload["is_active"],
            )

        async with self._db_session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT tenant_id, slug, daily_budget_usd, approval_ttl_s,
                           auto_approve_threshold, approval_categories, url_allowlist, is_active
                    FROM tenants
                    WHERE tenant_id = :tenant_id AND is_active = TRUE
                    """
                ),
                {"tenant_id": str(tenant_id)},
            )
            row = result.mappings().first()

        if row is None:
            raise TenantNotFoundError(f"Tenant {tenant_id} not found")

        tenant_config = TenantConfig(
            tenant_id=row["tenant_id"],
            slug=row["slug"],
            daily_budget_usd=row["daily_budget_usd"],
            approval_ttl_s=row["approval_ttl_s"],
            auto_approve_threshold=float(row["auto_approve_threshold"]),
            approval_categories=list(row["approval_categories"] or []),
            url_allowlist=list(row["url_allowlist"] or []),
            is_active=row["is_active"],
        )
        serialized = asdict(tenant_config)
        serialized["tenant_id"] = str(tenant_config.tenant_id)
        serialized["daily_budget_usd"] = str(tenant_config.daily_budget_usd)
        self._redis.setex(cache_key, self._ttl_seconds, json.dumps(serialized))
        return tenant_config

    async def invalidate(self, tenant_id: UUID) -> None:
        self._redis.delete(self._cache_key(tenant_id))

    def _cache_key(self, tenant_id: UUID) -> str:
        return f"tenant:{tenant_id}:config"
