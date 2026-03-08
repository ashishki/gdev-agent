"""Observability tests for tracing instrumentation."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import fakeredis

from app.agent import AgentService
from app.approval_store import RedisApprovalStore
from app.config import Settings
from app.llm_client import TriageResult
from app.schemas import (
    ClassificationResult,
    ExtractedFields,
    ProposedAction,
    WebhookRequest,
    WebhookResponse,
)
from app.store import EventStore


class _Span:
    def __init__(self, tracer: "_Tracer", name: str) -> None:
        self._tracer = tracer
        self.name = name
        self.attributes: dict[str, object] = {}

    def __enter__(self) -> "_Span":
        self._tracer.spans.append(self)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def set_attribute(self, name: str, value: object) -> None:
        self.attributes[name] = value

    def record_exception(self, _exc: BaseException) -> None:
        return None


class _Tracer:
    def __init__(self) -> None:
        self.spans: list[_Span] = []

    def start_as_current_span(self, name: str, **_kwargs) -> _Span:
        return _Span(self, name)


class _FakeLLMClient:
    def run_agent(
        self,
        text: str,
        user_id: str | None = None,
        max_turns: int = 5,
        tenant_id: str | None = None,
    ) -> TriageResult:
        _ = (text, user_id, max_turns, tenant_id)
        return TriageResult(
            classification=ClassificationResult(
                category="other", urgency="low", confidence=0.95
            ),
            extracted=ExtractedFields(user_id=user_id),
            draft_text="draft",
            input_tokens=120,
            output_tokens=80,
            turns_used=2,
        )


def test_agent_emits_required_pipeline_spans(monkeypatch) -> None:
    tracer = _Tracer()
    monkeypatch.setattr("app.agent.TRACER", tracer)

    agent = AgentService(
        settings=Settings(approval_categories=[], auto_approve_threshold=0.5),
        store=EventStore(sqlite_path=None),
        approval_store=RedisApprovalStore(fakeredis.FakeRedis(), ttl_seconds=3600),
        llm_client=_FakeLLMClient(),
    )
    tenant_id = str(uuid4())
    response = agent.process_webhook(
        WebhookRequest(text="hello", user_id="u1", tenant_id=tenant_id)
    )

    assert response.status == "executed"
    names = [span.name for span in tracer.spans]
    assert names == [
        "agent.input_guard",
        "agent.budget_check",
        "agent.llm_classify",
        "agent.propose_action",
        "agent.output_guard",
        "agent.route",
    ]
    llm_span = tracer.spans[2]
    assert llm_span.attributes["model"] == "claude-sonnet-4-6"
    assert llm_span.attributes["input_tokens"] == 120
    assert llm_span.attributes["output_tokens"] == 80
    assert llm_span.attributes["turns_used"] == 2
    assert "cost_usd" in llm_span.attributes


def test_main_webhook_wraps_request_in_http_root_span(monkeypatch) -> None:
    from app import main

    tracer = _Tracer()
    monkeypatch.setattr(main, "TRACER", tracer)
    monkeypatch.setattr(
        main, "OTEL_PROPAGATE", SimpleNamespace(extract=lambda *_: None)
    )
    main.app.state.dedup = SimpleNamespace(check=lambda *_: None, set=lambda *_: None)
    main.app.state.agent = SimpleNamespace(
        process_webhook=lambda *_args, **_kwargs: WebhookResponse(
            status="executed",
            classification=ClassificationResult(
                category="other", urgency="low", confidence=0.9
            ),
            extracted=ExtractedFields(user_id="u1"),
            action=ProposedAction(tool="create_ticket_and_reply", payload={}),
            draft_response="ok",
            action_result={},
        )
    )
    main.webhook(
        WebhookRequest(text="hello", tenant_id=str(uuid4())),
        request=SimpleNamespace(headers={}, state=SimpleNamespace()),
    )

    assert tracer.spans[0].name == "http.request"
    assert tracer.spans[1].name == "middleware.dedup"
