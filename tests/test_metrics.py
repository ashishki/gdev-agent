"""Metrics tests for Prometheus instrumentation."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from prometheus_client import REGISTRY

import fakeredis
from app.agent import AgentService
from app.approval_store import RedisApprovalStore
from app.config import Settings
from app.llm_client import TriageResult
from app.main import metrics
from app.schemas import (
    ClassificationResult,
    ExtractedFields,
    PendingDecision,
    ProposedAction,
    WebhookRequest,
)
from app.store import EventStore

UTC = timezone.utc


class _FakeLLMClient:
    def run_agent(
        self,
        text: str,
        user_id: str | None = None,
        max_turns: int = 5,
        tenant_id: str | None = None,
    ) -> TriageResult:
        _ = (text, max_turns, tenant_id)
        return TriageResult(
            classification=ClassificationResult(category="other", urgency="low", confidence=0.95),
            extracted=ExtractedFields(user_id=user_id),
            draft_text="draft",
            input_tokens=100,
            output_tokens=50,
            turns_used=2,
        )


def _sample(metric: str, labels: dict[str, str]) -> float:
    value = REGISTRY.get_sample_value(metric, labels=labels)
    return float(value) if value is not None else 0.0


def test_webhook_increments_request_and_token_metrics() -> None:
    tenant_id = str(uuid4())
    tenant_hash = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:16]
    model = "claude-sonnet-4-6"
    request_labels = {
        "status": "executed",
        "category": "other",
        "urgency": "low",
        "tenant_hash": tenant_hash,
    }
    input_labels = {"direction": "input", "model": model, "tenant_hash": tenant_hash}
    output_labels = {"direction": "output", "model": model, "tenant_hash": tenant_hash}
    before_requests = _sample("gdev_requests_total", request_labels)
    before_input = _sample("gdev_llm_tokens_total", input_labels)
    before_output = _sample("gdev_llm_tokens_total", output_labels)

    agent = AgentService(
        settings=Settings(
            approval_categories=[],
            auto_approve_threshold=0.5,
            llm_input_rate_per_1k=Decimal("0.003"),
            llm_output_rate_per_1k=Decimal("0.015"),
        ),
        store=EventStore(sqlite_path=None),
        approval_store=RedisApprovalStore(fakeredis.FakeRedis(), ttl_seconds=3600),
        llm_client=_FakeLLMClient(),
    )
    response = agent.process_webhook(
        WebhookRequest(text="hello", user_id="u1", tenant_id=tenant_id)
    )

    assert response.status == "executed"
    assert _sample("gdev_requests_total", request_labels) == before_requests + 1
    assert _sample("gdev_llm_tokens_total", input_labels) == before_input + 100
    assert _sample("gdev_llm_tokens_total", output_labels) == before_output + 50


def test_metrics_endpoint_returns_prometheus_text() -> None:
    response = metrics()
    body = response.body.decode("utf-8")

    assert response.status_code == 200
    assert "gdev_requests_total" in body
    assert "gdev_llm_tokens_total" in body
    assert "gdev_budget_utilization_ratio" in body
    assert "gdev_rca_clusters_active" in body
    assert "gdev_rca_run_duration_seconds" in body
    assert "gdev_rca_tickets_scanned" in body
    assert "gdev_embedding_duration_seconds" in body


def test_approval_store_updates_queue_depth_gauge() -> None:
    tenant_id = str(uuid4())
    tenant_hash = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:16]
    store = RedisApprovalStore(fakeredis.FakeRedis(), ttl_seconds=60)
    pending = PendingDecision(
        pending_id="pending-1",
        tenant_id=tenant_id,
        reason="manual",
        user_id="u1",
        expires_at=datetime.now(UTC) + timedelta(seconds=60),
        action=ProposedAction(tool="create_ticket_and_reply", payload={}),
        draft_response="draft",
    )
    before = _sample("gdev_approval_queue_depth", {"tenant_hash": tenant_hash})
    store.put_pending(pending)
    after_put = _sample("gdev_approval_queue_depth", {"tenant_hash": tenant_hash})
    store.pop_pending(tenant_id, "pending-1")
    after_pop = _sample("gdev_approval_queue_depth", {"tenant_hash": tenant_hash})

    assert after_put == before + 1
    assert after_pop == before
