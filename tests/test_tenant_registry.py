"""TenantRegistry cache and DB behavior tests."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.tenant_registry import TenantConfig, TenantNotFoundError, TenantRegistry


class _RedisStub:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.deleted: list[str] = []

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def setex(self, key: str, ttl_seconds: int, value: str) -> None:
        _ = ttl_seconds
        self.data[key] = value

    def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.data.pop(key, None)


class _ResultStub:
    def __init__(self, row: dict[str, object] | None) -> None:
        self._row = row

    def mappings(self) -> "_ResultStub":
        return self

    def first(self) -> dict[str, object] | None:
        return self._row


class _SessionStub:
    def __init__(self, row: dict[str, object] | None) -> None:
        self.row = row
        self.execute_calls: list[tuple[object, dict[str, object]]] = []

    async def __aenter__(self) -> "_SessionStub":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def execute(self, statement, params: dict[str, object]):
        self.execute_calls.append((statement, params))
        return _ResultStub(self.row)


class _SessionFactoryStub:
    def __init__(self, session: _SessionStub) -> None:
        self.session = session
        self.calls = 0

    def __call__(self) -> _SessionStub:
        self.calls += 1
        return self.session


def _row(tenant_id: UUID, is_active: bool = True) -> dict[str, object]:
    return {
        "tenant_id": tenant_id,
        "slug": "tenant-a",
        "daily_budget_usd": Decimal("12.3400"),
        "approval_ttl_s": 3600,
        "auto_approve_threshold": 0.9,
        "approval_categories": ["billing", "other"],
        "url_allowlist": ["kb.example.com"],
        "is_active": is_active,
    }


@pytest.mark.asyncio
async def test_cache_hit_returns_config_without_db_call() -> None:
    tenant_id = uuid4()
    redis_stub = _RedisStub()
    redis_stub.data[f"tenant:{tenant_id}:config"] = (
        '{"tenant_id": "' + str(tenant_id) + '", "slug": "tenant-a", '
        '"daily_budget_usd": "12.3400", "approval_ttl_s": 3600, '
        '"auto_approve_threshold": 0.9, "approval_categories": ["billing"], '
        '"url_allowlist": ["kb.example.com"], "is_active": true}'
    )
    session = _SessionStub(_row(tenant_id))
    session_factory = _SessionFactoryStub(session)
    registry = TenantRegistry(redis_stub, session_factory)

    config = await registry.get_tenant_config(tenant_id)

    assert isinstance(config, TenantConfig)
    assert config.tenant_id == tenant_id
    assert config.slug == "tenant-a"
    assert config.daily_budget_usd == Decimal("12.3400")
    assert session_factory.calls == 0


@pytest.mark.asyncio
async def test_cache_miss_reads_db_and_populates_cache() -> None:
    tenant_id = uuid4()
    redis_stub = _RedisStub()
    session = _SessionStub(_row(tenant_id))
    session_factory = _SessionFactoryStub(session)
    registry = TenantRegistry(redis_stub, session_factory)

    config = await registry.get_tenant_config(tenant_id)

    assert config.tenant_id == tenant_id
    assert session_factory.calls == 1
    assert len(session.execute_calls) == 1
    statement, params = session.execute_calls[0]
    assert "WHERE tenant_id = :tenant_id AND is_active = TRUE" in str(statement)
    assert params == {"tenant_id": str(tenant_id)}
    assert f"tenant:{tenant_id}:config" in redis_stub.data


@pytest.mark.asyncio
async def test_inactive_tenant_raises_not_found() -> None:
    tenant_id = uuid4()
    redis_stub = _RedisStub()
    session = _SessionStub(None)
    session_factory = _SessionFactoryStub(session)
    registry = TenantRegistry(redis_stub, session_factory)

    with pytest.raises(TenantNotFoundError):
        await registry.get_tenant_config(tenant_id)


@pytest.mark.asyncio
async def test_missing_tenant_raises_not_found() -> None:
    tenant_id = uuid4()
    registry = TenantRegistry(_RedisStub(), _SessionFactoryStub(_SessionStub(None)))

    with pytest.raises(TenantNotFoundError):
        await registry.get_tenant_config(tenant_id)


@pytest.mark.asyncio
async def test_invalidate_deletes_cache_key() -> None:
    tenant_id = uuid4()
    redis_stub = _RedisStub()
    key = f"tenant:{tenant_id}:config"
    redis_stub.data[key] = "cached"
    registry = TenantRegistry(redis_stub, _SessionFactoryStub(_SessionStub(None)))

    await registry.invalidate(tenant_id)

    assert key in redis_stub.deleted
    assert key not in redis_stub.data
