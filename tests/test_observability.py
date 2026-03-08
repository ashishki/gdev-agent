"""Observability trace tests for webhook processing."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from uuid import uuid4

from app.agent import AgentService
from app.config import Settings
from app.main import webhook
from app.schemas import ClassificationResult, ExtractedFields, WebhookRequest


@dataclass
class _RecordedSpan:
    name: str
    attributes: dict[str, object] = field(default_factory=dict)

    def __enter__(self) -> "_RecordedSpan":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value

    def record_exception(self, _exc: BaseException) -> None:
        return None


class _RecordingTracer:
    def __init__(self) -> None:
        self.spans: list[_RecordedSpan] = []

    def start_as_current_span(self, name: str, **_kwargs) -> _RecordedSpan:
        span = _RecordedSpan(name=name)
        self.spans.append(span)
        return span


class _StoreStub:
    _db_session_factory = None

    def log_event(self, _event_type: str, _payload: dict[str, object]) -> None:
        return None

    def persist_pipeline_run(self, *_args, **_kwargs) -> str:
        return "ticket-1"


class _ApprovalStoreStub:
    def put_pending(self, _pending) -> None:
        return None


class _LLMStub:
    def run_agent(self, _text: str, user_id: str | None, tenant_id: str | None = None):
        _ = tenant_id
        return SimpleNamespace(
            classification=ClassificationResult(
                category="gameplay_question", urgency="low", confidence=0.92
            ),
            extracted=ExtractedFields(user_id=user_id, keywords=["help"]),
            draft_text="Thanks, we are reviewing this.",
            input_tokens=123,
            output_tokens=45,
            turns_used=2,
        )


def test_webhook_trace_contains_required_agent_spans_and_attributes(
    monkeypatch,
) -> None:
    tracer = _RecordingTracer()
    settings = Settings(
        anthropic_api_key="test-key",
        output_guard_enabled=False,
        approval_categories=["billing"],
    )

    import app.agent as agent_module
    import app.main as main_module

    monkeypatch.setattr(agent_module, "TRACER", tracer)
    monkeypatch.setattr(main_module, "TRACER", tracer)
    monkeypatch.setattr(main_module, "OTEL_PROPAGATE", None)

    agent = AgentService(
        settings=settings,
        store=_StoreStub(),
        approval_store=_ApprovalStoreStub(),
        llm_client=_LLMStub(),
    )

    dedup_cache = SimpleNamespace(
        check=lambda _message_id: None,
        set=lambda _message_id, _body: None,
    )
    main_module.app.state.agent = agent
    main_module.app.state.dedup = dedup_cache

    request = SimpleNamespace(headers={}, state=SimpleNamespace())
    payload = WebhookRequest(
        tenant_id=str(uuid4()),
        user_id="user-123",
        text="Need help with quest progression",
        message_id="msg-1",
    )

    response = webhook(payload, request)

    assert response.status == "executed"
    span_names = [span.name for span in tracer.spans]
    assert "http.request" in span_names
    assert "agent.input_guard" in span_names
    assert "agent.budget_check" in span_names
    assert "agent.llm_classify" in span_names
    assert "agent.propose_action" in span_names
    assert "agent.output_guard" in span_names
    assert "agent.route" in span_names

    llm_span = next(span for span in tracer.spans if span.name == "agent.llm_classify")
    assert llm_span.attributes["model"] == settings.anthropic_model
    assert llm_span.attributes["input_tokens"] == 123
    assert llm_span.attributes["output_tokens"] == 45
    assert llm_span.attributes["cost_usd"] > 0
    assert llm_span.attributes["turns_used"] == 2


def test_agent_span_attributes_do_not_include_raw_text_or_user_id(monkeypatch) -> None:
    tracer = _RecordingTracer()
    settings = Settings(
        anthropic_api_key="test-key",
        output_guard_enabled=False,
        approval_categories=["billing"],
    )

    import app.agent as agent_module

    monkeypatch.setattr(agent_module, "TRACER", tracer)

    agent = AgentService(
        settings=settings,
        store=_StoreStub(),
        approval_store=_ApprovalStoreStub(),
        llm_client=_LLMStub(),
    )

    response = agent.process_webhook(
        WebhookRequest(
            tenant_id=str(uuid4()),
            user_id="user-123",
            text="Player email is demo@example.com and account is blocked",
        ),
        message_id="msg-2",
    )

    assert response.status == "executed"
    for span in tracer.spans:
        for key, value in span.attributes.items():
            assert "raw_text" not in key
            assert key != "user_id"
            if isinstance(value, str):
                assert "demo@example.com" not in value
                assert "Player email is" not in value
                assert value != "user-123"
