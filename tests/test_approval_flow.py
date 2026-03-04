"""Approval flow regression tests for critical review findings."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import fakeredis
import pytest
from fastapi import HTTPException

from app.agent import AgentService
from app.approval_store import RedisApprovalStore
from app.config import Settings
from app.llm_client import TriageResult
from app.schemas import (
    ApproveRequest,
    ClassificationResult,
    ExtractedFields,
    PendingDecision,
    ProposedAction,
    WebhookRequest,
)
from app.store import EventStore


class FakeLLMClient:
    """Deterministic LLM client used for unit tests."""

    def run_agent(self, text: str, user_id: str | None = None, max_turns: int = 5) -> TriageResult:
        _ = (text, max_turns)
        return TriageResult(
            classification=ClassificationResult(
                category="billing",
                urgency="medium",
                confidence=0.95,
            ),
            extracted=ExtractedFields(user_id=user_id, platform="unknown"),
            draft_text="We are reviewing your billing request.",
            input_tokens=100,
            output_tokens=50,
        )


def test_approve_executes_with_original_user_id() -> None:
    """Approved pending action must send reply to original webhook user_id."""
    settings = Settings(approval_categories=["billing"], approval_ttl_seconds=3600)
    approval_store = RedisApprovalStore(fakeredis.FakeRedis(), ttl_seconds=3600)
    agent = AgentService(
        settings=settings,
        store=EventStore(sqlite_path=None),
        approval_store=approval_store,
        llm_client=FakeLLMClient(),
    )

    response = agent.process_webhook(
        WebhookRequest(
            text="Charged twice for a purchase",
            user_id="user-123",
            tenant_id="tenant-a",
        )
    )
    assert response.pending is not None
    assert response.pending.tenant_id == "tenant-a"

    approve_response = agent.approve(
        ApproveRequest(pending_id=response.pending.pending_id, approved=True, reviewer="rev-1"),
        jwt_tenant_id="tenant-a",
    )
    assert approve_response.result is not None
    assert approve_response.result["reply"]["user_id"] == "user-123"


def test_redis_pending_expired_returns_none() -> None:
    """Expired pending decisions must be evicted and treated as not found."""
    redis_client = fakeredis.FakeRedis()
    store = RedisApprovalStore(redis_client, ttl_seconds=3600)
    pending = PendingDecision(
        pending_id="expired-1",
        tenant_id="tenant-a",
        reason="manual",
        user_id="u-1",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
        action=ProposedAction(tool="create_ticket_and_reply", payload={}),
        draft_response="draft",
    )
    store.put_pending(pending)

    assert store.pop_pending("expired-1") is None


def test_approve_forbidden_on_cross_tenant_pending() -> None:
    settings = Settings(approval_categories=["billing"], approval_ttl_seconds=3600)
    approval_store = RedisApprovalStore(fakeredis.FakeRedis(), ttl_seconds=3600)
    agent = AgentService(
        settings=settings,
        store=EventStore(sqlite_path=None),
        approval_store=approval_store,
        llm_client=FakeLLMClient(),
    )

    response = agent.process_webhook(
        WebhookRequest(text="Charged twice for a purchase", user_id="user-123", tenant_id="tenant-a")
    )
    assert response.pending is not None
    assert response.pending.tenant_id == "tenant-a"

    with pytest.raises(HTTPException) as exc:
        agent.approve(
            ApproveRequest(pending_id=response.pending.pending_id, approved=True, reviewer="rev-1"),
            jwt_tenant_id="tenant-b",
        )
    assert exc.value.status_code == 403
    assert approval_store.get_pending(response.pending.pending_id) is not None


def test_approve_forbidden_when_jwt_tenant_missing() -> None:
    settings = Settings(approval_categories=["billing"], approval_ttl_seconds=3600)
    approval_store = RedisApprovalStore(fakeredis.FakeRedis(), ttl_seconds=3600)
    agent = AgentService(
        settings=settings,
        store=EventStore(sqlite_path=None),
        approval_store=approval_store,
        llm_client=FakeLLMClient(),
    )

    response = agent.process_webhook(
        WebhookRequest(text="Charged twice for a purchase", user_id="user-123", tenant_id="tenant-a")
    )
    assert response.pending is not None

    with pytest.raises(HTTPException) as exc:
        agent.approve(
            ApproveRequest(pending_id=response.pending.pending_id, approved=True, reviewer="rev-1"),
            jwt_tenant_id=None,
        )
    assert exc.value.status_code == 403
