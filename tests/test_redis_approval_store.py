"""Redis approval store tests."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from uuid import uuid4

import fakeredis

import app.approval_store
from app.approval_store import RedisApprovalStore
from app.schemas import PendingDecision, ProposedAction


UTC = timezone.utc

def _pending(pid: str, expires_delta: int = 60) -> PendingDecision:
    return PendingDecision(
        pending_id=pid,
        tenant_id="tenant-a",
        reason="manual",
        user_id="u1",
        expires_at=datetime.now(UTC) + timedelta(seconds=expires_delta),
        action=ProposedAction(tool="create_ticket_and_reply", payload={}),
        draft_response="draft",
    )


def test_put_and_get_pending_roundtrip() -> None:
    redis_client = fakeredis.FakeRedis()
    store = RedisApprovalStore(redis_client, ttl_seconds=120)

    store.put_pending(_pending("p1"))
    got = store.get_pending("tenant-a", "p1")

    assert got is not None
    assert got.pending_id == "p1"


def test_pop_pending_deletes_key() -> None:
    redis_client = fakeredis.FakeRedis()
    store = RedisApprovalStore(redis_client, ttl_seconds=120)

    store.put_pending(_pending("p2"))
    got = store.pop_pending("tenant-a", "p2")

    assert got is not None
    assert store.get_pending("tenant-a", "p2") is None


def test_expired_pending_returns_none() -> None:
    redis_client = fakeredis.FakeRedis()
    store = RedisApprovalStore(redis_client, ttl_seconds=120)

    store.put_pending(_pending("p3", expires_delta=-10))
    assert store.pop_pending("tenant-a", "p3") is None


def test_ttl_is_set() -> None:
    redis_client = fakeredis.FakeRedis()
    store = RedisApprovalStore(redis_client, ttl_seconds=777)

    store.put_pending(_pending("p4"))
    ttl = redis_client.ttl("tenant-a:pending:p4")

    assert ttl > 0
    assert ttl <= 777


def test_key_builder_uses_tenant_first_order() -> None:
    assert RedisApprovalStore._key("tenant-a", "p6") == "tenant-a:pending:p6"


def test_pending_is_isolated_by_tenant() -> None:
    redis_client = fakeredis.FakeRedis()
    store = RedisApprovalStore(redis_client, ttl_seconds=120)

    store.put_pending(_pending("p5"))

    assert store.get_pending("tenant-b", "p5") is None
    assert store.pop_pending("tenant-b", "p5") is None
    assert store.get_pending("tenant-a", "p5") is not None


class _ResultStub:
    def __init__(self, row: dict[str, object] | None = None) -> None:
        self._row = row

    def mappings(self) -> "_ResultStub":
        return self

    def first(self) -> dict[str, object] | None:
        return self._row


class _SessionStub:
    def __init__(self, execute_calls: list[tuple[str, dict[str, object]]]) -> None:
        self._execute_calls = execute_calls

    async def __aenter__(self) -> "_SessionStub":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def begin(self):
        return self

    async def execute(self, statement, params):
        self._execute_calls.append((str(statement), dict(params or {})))
        return _ResultStub({"ok": True})


class _SessionFactoryStub:
    def __init__(self) -> None:
        self.execute_calls: list[tuple[str, dict[str, object]]] = []

    def __call__(self) -> _SessionStub:
        return _SessionStub(self.execute_calls)


def test_put_pending_dual_writes_to_postgres_when_session_factory_present() -> None:
    redis_client = fakeredis.FakeRedis()
    session_factory = _SessionFactoryStub()
    store = RedisApprovalStore(
        redis_client,
        ttl_seconds=120,
        db_session_factory=session_factory,
    )
    tenant_id = str(uuid4())
    pending_id = str(uuid4())

    store.put_pending(
        PendingDecision(
            pending_id=pending_id,
            tenant_id=tenant_id,
            reason="manual",
            user_id="u1",
            expires_at=datetime.now(UTC) + timedelta(seconds=60),
            action=ProposedAction(tool="create_ticket_and_reply", payload={}),
            draft_response="draft",
        )
    )

    statements = [sql.lower() for sql, _ in session_factory.execute_calls]
    assert any("set local app.current_tenant_id" in sql for sql in statements)
    assert any("insert into pending_decisions" in sql for sql in statements)


def test_put_pending_uses_shared_run_blocking(monkeypatch) -> None:
    redis_client = fakeredis.FakeRedis()
    session_factory = _SessionFactoryStub()
    store = RedisApprovalStore(
        redis_client,
        ttl_seconds=120,
        db_session_factory=session_factory,
    )
    called = {"value": False}

    def fake_run_blocking(coroutine):
        called["value"] = True
        asyncio.run(coroutine)

    monkeypatch.setattr(app.approval_store, "run_blocking", fake_run_blocking)

    store.put_pending(
        PendingDecision(
            pending_id=str(uuid4()),
            tenant_id=str(uuid4()),
            reason="manual",
            user_id="u1",
            expires_at=datetime.now(UTC) + timedelta(seconds=60),
            action=ProposedAction(tool="create_ticket_and_reply", payload={}),
            draft_response="draft",
        )
    )

    assert called["value"] is True
