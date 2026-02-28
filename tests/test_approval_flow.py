"""Approval flow regression tests for critical review findings."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.agent import AgentService
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
        )


def test_approve_executes_with_original_user_id() -> None:
    """Approved pending action must send reply to original webhook user_id."""
    settings = Settings(approval_categories=["billing"], approval_ttl_seconds=3600)
    store = EventStore(sqlite_path=None)
    agent = AgentService(settings=settings, store=store, llm_client=FakeLLMClient())

    response = agent.process_webhook(
        WebhookRequest(
            text="Charged twice for a purchase",
            user_id="user-123",
        )
    )
    assert response.pending is not None

    approve_response = agent.approve(ApproveRequest(pending_id=response.pending.pending_id, approved=True))
    assert approve_response.result is not None
    assert approve_response.result["reply"]["user_id"] == "user-123"


def test_pop_pending_returns_none_for_expired_entry() -> None:
    """Expired pending decisions must be evicted and treated as not found."""
    store = EventStore(sqlite_path=None)
    pending = PendingDecision(
        pending_id="expired-1",
        reason="manual",
        user_id="u-1",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
        action=ProposedAction(tool="create_ticket_and_reply", payload={}),
        draft_response="draft",
    )
    store.put_pending(pending)

    assert store.pop_pending("expired-1") is None
