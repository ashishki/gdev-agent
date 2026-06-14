"""Approval flow regression tests for critical review findings."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import fakeredis
from app.agent import AgentService
from app.approval_store import RedisApprovalStore
from app.config import Settings
from app.exceptions import AgentError
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

UTC = timezone.utc


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


class CapturingStore(EventStore):
    def __init__(self) -> None:
        super().__init__(sqlite_path=None)
        self.events: list[tuple[str, dict[str, object]]] = []

    def log_event(self, event_type: str, payload: dict[str, object]) -> None:
        self.events.append((event_type, payload))


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

    assert store.pop_pending("tenant-a", "expired-1") is None


def test_expired_approval_returns_404_without_action_execution(caplog) -> None:
    settings = Settings(approval_categories=["billing"], approval_ttl_seconds=3600)
    approval_store = RedisApprovalStore(fakeredis.FakeRedis(), ttl_seconds=3600)
    store = CapturingStore()
    agent = AgentService(
        settings=settings,
        store=store,
        approval_store=approval_store,
        llm_client=FakeLLMClient(),
    )
    pending = PendingDecision(
        pending_id="expired-agent-1",
        tenant_id="tenant-a",
        reason="manual",
        user_id="user-123",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
        action=ProposedAction(tool="create_ticket_and_reply", payload={}, risky=True),
        draft_response="draft",
    )
    approval_store.put_pending(pending)

    with caplog.at_level("INFO", logger="app.approval_store"):
        with pytest.raises(AgentError) as exc:
            agent.approve(
                ApproveRequest(pending_id=pending.pending_id, approved=True, reviewer="rev-1"),
                jwt_tenant_id="tenant-a",
            )

    assert exc.value.status_code == 404
    assert exc.value.detail == "pending_id not found"
    assert store.events == []
    assert any(getattr(record, "event", None) == "pending_expired" for record in caplog.records)
    failure_doc = Path("docs/FAILURE_MODES.md").read_text(encoding="utf-8")
    assert "FM_APPROVAL_TTL_EXPIRED" in failure_doc
    assert "tests/test_approval_flow.py" in failure_doc


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
        WebhookRequest(
            text="Charged twice for a purchase",
            user_id="user-123",
            tenant_id="tenant-a",
        )
    )
    assert response.pending is not None
    assert response.pending.tenant_id == "tenant-a"

    with pytest.raises(AgentError) as exc:
        agent.approve(
            ApproveRequest(pending_id=response.pending.pending_id, approved=True, reviewer="rev-1"),
            jwt_tenant_id="tenant-b",
        )
    assert exc.value.status_code == 404
    assert approval_store.get_pending("tenant-a", response.pending.pending_id) is not None


def test_cross_tenant_approval_does_not_execute_action() -> None:
    settings = Settings(approval_categories=["billing"], approval_ttl_seconds=3600)
    approval_store = RedisApprovalStore(fakeredis.FakeRedis(), ttl_seconds=3600)
    store = CapturingStore()
    agent = AgentService(
        settings=settings,
        store=store,
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
    store.events.clear()

    with pytest.raises(AgentError) as exc:
        agent.approve(
            ApproveRequest(pending_id=response.pending.pending_id, approved=True, reviewer="rev-1"),
            jwt_tenant_id="tenant-b",
        )

    assert exc.value.status_code == 404
    assert store.events == []
    assert approval_store.get_pending("tenant-a", response.pending.pending_id) is not None
    failure_doc = Path("docs/FAILURE_MODES.md").read_text(encoding="utf-8")
    assert "FM_CROSS_TENANT_APPROVAL" in failure_doc
    assert "tests/test_approval_flow.py" in failure_doc


def test_tenant_a_cannot_approve_tenant_b_pending_action() -> None:
    settings = Settings(approval_categories=["billing"], approval_ttl_seconds=3600)
    approval_store = RedisApprovalStore(fakeredis.FakeRedis(), ttl_seconds=3600)
    store = CapturingStore()
    agent = AgentService(
        settings=settings,
        store=store,
        approval_store=approval_store,
        llm_client=FakeLLMClient(),
    )
    response = agent.process_webhook(
        WebhookRequest(
            text="Charged twice for a purchase",
            user_id="user-456",
            tenant_id="tenant-b",
        )
    )
    assert response.pending is not None
    store.events.clear()

    with pytest.raises(AgentError) as exc:
        agent.approve(
            ApproveRequest(pending_id=response.pending.pending_id, approved=True, reviewer="rev-1"),
            jwt_tenant_id="tenant-a",
        )

    assert exc.value.status_code == 404
    assert store.events == []
    assert approval_store.get_pending("tenant-b", response.pending.pending_id) is not None
    failure_doc = Path("docs/FAILURE_MODES.md").read_text(encoding="utf-8")
    assert "FM_CROSS_TENANT_APPROVAL" in failure_doc
    assert "test_tenant_a_cannot_approve_tenant_b_pending_action" in failure_doc


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
        WebhookRequest(
            text="Charged twice for a purchase",
            user_id="user-123",
            tenant_id="tenant-a",
        )
    )
    assert response.pending is not None

    with pytest.raises(AgentError) as exc:
        agent.approve(
            ApproveRequest(pending_id=response.pending.pending_id, approved=True, reviewer="rev-1"),
            jwt_tenant_id=None,
        )
    assert exc.value.status_code == 403


def test_double_approve_returns_404() -> None:
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

    first = agent.approve(
        ApproveRequest(pending_id=response.pending.pending_id, approved=True, reviewer="rev-1"),
        jwt_tenant_id="tenant-a",
    )
    assert first.status == "approved"

    with pytest.raises(AgentError) as exc:
        agent.approve(
            ApproveRequest(pending_id=response.pending.pending_id, approved=True, reviewer="rev-1"),
            jwt_tenant_id="tenant-a",
        )
    assert exc.value.status_code == 404
