"""Redis approval store tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import fakeredis

from app.approval_store import RedisApprovalStore
from app.schemas import PendingDecision, ProposedAction


def _pending(pid: str, expires_delta: int = 60) -> PendingDecision:
    return PendingDecision(
        pending_id=pid,
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
    got = store.get_pending("p1")

    assert got is not None
    assert got.pending_id == "p1"


def test_pop_pending_deletes_key() -> None:
    redis_client = fakeredis.FakeRedis()
    store = RedisApprovalStore(redis_client, ttl_seconds=120)

    store.put_pending(_pending("p2"))
    got = store.pop_pending("p2")

    assert got is not None
    assert store.get_pending("p2") is None


def test_expired_pending_returns_none() -> None:
    redis_client = fakeredis.FakeRedis()
    store = RedisApprovalStore(redis_client, ttl_seconds=120)

    store.put_pending(_pending("p3", expires_delta=-10))
    assert store.pop_pending("p3") is None


def test_ttl_is_set() -> None:
    redis_client = fakeredis.FakeRedis()
    store = RedisApprovalStore(redis_client, ttl_seconds=777)

    store.put_pending(_pending("p4"))
    ttl = redis_client.ttl("pending:p4")

    assert ttl > 0
    assert ttl <= 777
