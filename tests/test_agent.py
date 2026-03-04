"""Agent service tests for LLM draft and cost tracking."""

from __future__ import annotations

from decimal import Decimal
import hashlib
import fakeredis
import logging
from unittest.mock import Mock
from uuid import uuid4

from app.agent import AgentService
from app.approval_store import RedisApprovalStore
from app.config import Settings
from app.llm_client import TriageResult
from app.schemas import ApproveRequest, ClassificationResult, ExtractedFields, WebhookRequest
from app.store import EventStore


class FakeLLMClient:
    def run_agent(self, text: str, user_id: str | None = None, max_turns: int = 5) -> TriageResult:
        _ = (text, max_turns)
        return TriageResult(
            classification=ClassificationResult(category="other", urgency="low", confidence=0.95),
            extracted=ExtractedFields(user_id=user_id),
            draft_text="LLM draft response",
            input_tokens=100,
            output_tokens=50,
        )


class CapturingStore(EventStore):
    def __init__(self) -> None:
        super().__init__(sqlite_path=None)
        self.events: list[tuple[str, dict[str, object]]] = []

    def log_event(self, event_type: str, payload: dict[str, object]) -> None:
        self.events.append((event_type, payload))


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    def begin(self):
        return self

    async def execute(self, _query, _params=None) -> None:
        return None


class _FailingCostLedger:
    def __init__(self) -> None:
        self.record_calls = 0

    async def check_budget(self, _tenant_id, _db) -> None:
        return None

    async def record(self, *, tenant_id, day, input_tokens, output_tokens, cost_usd, db) -> None:
        _ = (tenant_id, day, input_tokens, output_tokens, cost_usd, db)
        self.record_calls += 1
        raise RuntimeError("db down")


class _CostLedgerStore(CapturingStore):
    def __init__(self) -> None:
        super().__init__()
        self._db_session_factory = lambda: _FakeSession()

    def persist_pipeline_run(self, *args, **kwargs):
        _ = (args, kwargs)
        return None


def test_webhook_uses_llm_draft_and_tracks_cost() -> None:
    settings = Settings(
        approval_categories=[],
        auto_approve_threshold=0.5,
        llm_input_rate_per_1k=Decimal("0.003"),
        llm_output_rate_per_1k=Decimal("0.015"),
    )
    store = CapturingStore()
    agent = AgentService(
        settings=settings,
        store=store,
        approval_store=RedisApprovalStore(fakeredis.FakeRedis(), ttl_seconds=3600),
        llm_client=FakeLLMClient(),
    )

    audit_entries = []
    agent._append_audit_async = lambda entry: audit_entries.append(entry)  # type: ignore[method-assign]

    response = agent.process_webhook(WebhookRequest(text="hello", user_id="u1"))

    assert response.draft_response == "LLM draft response"
    assert audit_entries[0].cost_usd > 0
    expected_cost = float(
        (Decimal(100) / Decimal(1000)) * Decimal("0.003")
        + (Decimal(50) / Decimal(1000)) * Decimal("0.015")
    )
    assert round(audit_entries[0].cost_usd, 6) == round(expected_cost, 6)

    event_payload = [payload for event, payload in store.events if event == "action_executed"][-1]
    assert event_payload["input_tokens"] == 100
    assert event_payload["output_tokens"] == 50


def test_approval_notification_failure_logs_exc_info(caplog) -> None:
    settings = Settings(
        approval_categories=["other"],
        telegram_approval_chat_id="chat-1",
        auto_approve_threshold=0.5,
    )
    store = CapturingStore()
    telegram_client = Mock()
    telegram_client.send_approval_request.side_effect = RuntimeError("telegram down")
    agent = AgentService(
        settings=settings,
        store=store,
        approval_store=RedisApprovalStore(fakeredis.FakeRedis(), ttl_seconds=3600),
        llm_client=FakeLLMClient(),
        telegram_client=telegram_client,
    )

    with caplog.at_level(logging.WARNING):
        response = agent.process_webhook(WebhookRequest(text="hello", user_id="u1"))

    assert response.status == "pending"
    record = next(r for r in caplog.records if r.msg == "failed sending approval notification")
    assert record.exc_info is not None


def test_cost_ledger_record_failure_is_logged_and_non_fatal(caplog) -> None:
    settings = Settings(
        approval_categories=[],
        auto_approve_threshold=0.5,
    )
    store = _CostLedgerStore()
    failing_ledger = _FailingCostLedger()
    agent = AgentService(
        settings=settings,
        store=store,
        approval_store=RedisApprovalStore(fakeredis.FakeRedis(), ttl_seconds=3600),
        llm_client=FakeLLMClient(),
        cost_ledger=failing_ledger,
    )

    with caplog.at_level(logging.WARNING):
        response = agent.process_webhook(WebhookRequest(text="hello", user_id="u1", tenant_id=str(uuid4())))

    assert response.status == "executed"
    assert failing_ledger.record_calls == 1
    record = next(r for r in caplog.records if r.msg == "failed recording llm cost")
    assert record.exc_info is not None


def test_approve_hashes_reviewer_in_logs_and_audit() -> None:
    settings = Settings(
        approval_categories=["other"],
        auto_approve_threshold=0.5,
    )
    store = CapturingStore()
    approval_store = RedisApprovalStore(fakeredis.FakeRedis(), ttl_seconds=3600)
    agent = AgentService(
        settings=settings,
        store=store,
        approval_store=approval_store,
        llm_client=FakeLLMClient(),
    )
    audit_entries = []
    agent._append_audit_async = lambda entry: audit_entries.append(entry)  # type: ignore[method-assign]

    response = agent.process_webhook(
        WebhookRequest(text="hello", user_id="u1", tenant_id="11111111-1111-1111-1111-111111111111")
    )
    assert response.pending is not None

    raw_reviewer = "raw_user_123"
    expected_hash = hashlib.sha256(raw_reviewer.encode()).hexdigest()[:16]
    approve_response = agent.approve(
        ApproveRequest(
            pending_id=response.pending.pending_id,
            approved=True,
            reviewer=raw_reviewer,
        ),
        jwt_tenant_id="11111111-1111-1111-1111-111111111111",
    )
    assert approve_response.status == "approved"

    approved_payload = [payload for event, payload in store.events if event == "pending_approved"][-1]
    assert approved_payload["reviewer"] == expected_hash
    assert raw_reviewer not in str(approved_payload)

    assert audit_entries[0].approved_by == expected_hash
    assert len(audit_entries[0].approved_by) == 16


def test_approve_keeps_approved_by_none_when_reviewer_missing() -> None:
    settings = Settings(
        approval_categories=["other"],
        auto_approve_threshold=0.5,
    )
    store = CapturingStore()
    approval_store = RedisApprovalStore(fakeredis.FakeRedis(), ttl_seconds=3600)
    agent = AgentService(
        settings=settings,
        store=store,
        approval_store=approval_store,
        llm_client=FakeLLMClient(),
    )
    audit_entries = []
    agent._append_audit_async = lambda entry: audit_entries.append(entry)  # type: ignore[method-assign]

    response = agent.process_webhook(
        WebhookRequest(text="hello", user_id="u1", tenant_id="22222222-2222-2222-2222-222222222222")
    )
    assert response.pending is not None

    approve_response = agent.approve(
        ApproveRequest(
            pending_id=response.pending.pending_id,
            approved=True,
            reviewer=None,
        ),
        jwt_tenant_id="22222222-2222-2222-2222-222222222222",
    )
    assert approve_response.status == "approved"
    assert audit_entries[0].approved_by is None
