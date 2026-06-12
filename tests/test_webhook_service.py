"""Unit tests for the webhook service layer."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

import fakeredis
from app.agent import AgentService
from app.approval_store import RedisApprovalStore
from app.config import Settings
from app.dedup import DedupCache
from app.exceptions import AgentError
from app.llm_client import TriageResult
from app.schemas import (
    ClassificationResult,
    ExtractedFields,
    ProposedAction,
    WebhookRequest,
    WebhookResponse,
)
from app.services.webhook_service import WebhookService
from app.store import EventStore


class _SpanStub:
    def __init__(self, name: str) -> None:
        self.name = name
        self.attributes: dict[str, object] = {}
        self.exceptions: list[BaseException] = []

    def __enter__(self) -> "_SpanStub":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        return False

    def set_attribute(self, name: str, value: object) -> None:
        self.attributes[name] = value

    def record_exception(self, exc: BaseException) -> None:
        self.exceptions.append(exc)


class _TracerStub:
    def __init__(self) -> None:
        self.spans: list[_SpanStub] = []

    def start_as_current_span(self, name: str, **_kwargs: object) -> _SpanStub:
        span = _SpanStub(name)
        self.spans.append(span)
        return span


class _DedupStub:
    def __init__(self, cached: str | None = None) -> None:
        self.cached = cached
        self.check_calls: list[tuple[str, str]] = []
        self.set_calls: list[tuple[str, str, str]] = []

    def check(self, tenant_id: str, message_id: str) -> str | None:
        self.check_calls.append((tenant_id, message_id))
        return self.cached

    def set(self, tenant_id: str, message_id: str, body: str) -> None:
        self.set_calls.append((tenant_id, message_id, body))


class _BillingLLMClient:
    def __init__(self) -> None:
        self.calls = 0

    def run_agent(
        self,
        text: str,
        user_id: str | None = None,
        max_turns: int = 5,
        tenant_id: str | None = None,
    ) -> TriageResult:
        _ = (text, max_turns, tenant_id)
        self.calls += 1
        return TriageResult(
            classification=ClassificationResult(
                category="billing", urgency="medium", confidence=0.95
            ),
            extracted=ExtractedFields(user_id=user_id),
            draft_text="We will review the billing issue.",
            input_tokens=80,
            output_tokens=30,
        )


class _CostResultStub:
    def mappings(self) -> "_CostResultStub":
        return self

    def first(self) -> dict[str, str]:
        return {"cost_usd": "0.001", "daily_budget_usd": "10.0"}


class _CostSessionStub:
    async def __aenter__(self) -> "_CostSessionStub":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        return False

    def begin(self) -> "_CostSessionStub":
        return self

    async def execute(self, _statement, _params=None) -> _CostResultStub:
        return _CostResultStub()


class _CostSessionFactoryStub:
    def __call__(self) -> _CostSessionStub:
        return _CostSessionStub()


class _CountingCostLedger:
    def __init__(self) -> None:
        self.check_calls = 0
        self.record_calls = 0

    async def check_budget(self, _tenant_id, _db) -> None:
        self.check_calls += 1

    async def record(self, *, tenant_id, day, input_tokens, output_tokens, cost_usd, db) -> None:
        _ = (tenant_id, day, input_tokens, output_tokens, cost_usd, db)
        self.record_calls += 1


class _CapturingStore(EventStore):
    def __init__(self) -> None:
        super().__init__(sqlite_path=None)
        self._db_session_factory = _CostSessionFactoryStub()
        self.events: list[tuple[str, dict[str, object]]] = []
        self.pipeline_runs: list[dict[str, object]] = []

    def log_event(self, event_type: str, payload: dict[str, object]) -> None:
        self.events.append((event_type, payload))

    def persist_pipeline_run(self, *args, **kwargs):
        self.pipeline_runs.append({"args": args, "kwargs": kwargs})
        return "ticket-1"


def _response() -> WebhookResponse:
    return WebhookResponse(
        status="executed",
        classification=ClassificationResult(category="other", urgency="low", confidence=0.9),
        extracted=ExtractedFields(),
        action=ProposedAction(tool="create_ticket_and_reply", payload={}, risky=False),
        draft_response="ok",
        action_result={"ok": True},
        pending=None,
    )


def _request(tenant_id: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        headers={},
        state=SimpleNamespace(tenant_id=tenant_id, trace_context=None),
    )


def test_handle_successful_flow() -> None:
    tenant_id = str(uuid4())
    response = _response()
    calls: list[tuple[WebhookRequest, str | None]] = []

    agent = SimpleNamespace(
        process_webhook=lambda payload, message_id=None: (
            calls.append((payload, message_id)) or response
        )
    )
    dedup = _DedupStub()
    service = WebhookService(agent, dedup, _TracerStub(), Settings(anthropic_api_key="k"))

    payload = WebhookRequest(text="hello", tenant_id=tenant_id, message_id="msg-1")
    result = service.handle(payload, _request())

    assert result == response
    assert calls[0][0].tenant_id == tenant_id
    assert calls[0][1] == "msg-1"
    assert dedup.check_calls == [(tenant_id, "msg-1")]
    assert dedup.set_calls == [(tenant_id, "msg-1", response.model_dump_json())]


def test_handle_returns_cached_response_on_dedup_hit() -> None:
    tenant_id = str(uuid4())
    cached = _response()
    agent = SimpleNamespace(
        process_webhook=lambda *_args, **_kwargs: pytest.fail("agent should not run")
    )
    dedup = _DedupStub(cached=cached.model_dump_json())
    service = WebhookService(agent, dedup, _TracerStub(), Settings(anthropic_api_key="k"))

    result = service.handle(
        WebhookRequest(text="hello", tenant_id=tenant_id, message_id="msg-1"),
        _request(),
    )

    assert result == cached
    assert dedup.set_calls == []


def test_duplicate_webhook_replay_is_idempotent_for_side_effects() -> None:
    tenant_id = str(uuid4())
    redis_client = fakeredis.FakeRedis()
    approval_store = RedisApprovalStore(redis_client, ttl_seconds=3600)
    llm_client = _BillingLLMClient()
    cost_ledger = _CountingCostLedger()
    store = _CapturingStore()
    settings = Settings(
        approval_categories=["billing"],
        auto_approve_threshold=0.85,
        anthropic_api_key="k",
    )
    agent = AgentService(
        settings=settings,
        store=store,
        approval_store=approval_store,
        llm_client=llm_client,
        cost_ledger=cost_ledger,
    )
    service = WebhookService(agent, DedupCache(redis_client), _TracerStub(), settings)
    payload = WebhookRequest(
        text="I was charged twice for coins.",
        tenant_id=tenant_id,
        message_id="duplicate-webhook-01",
        user_id="player-1",
    )

    first = service.handle(payload, _request())
    second = service.handle(payload, _request())

    assert first.status == "pending"
    assert second == first
    assert llm_client.calls == 1
    assert cost_ledger.check_calls == 1
    assert cost_ledger.record_calls == 1
    assert len(store.pipeline_runs) == 1
    assert [event for event, _payload in store.events] == ["pending_created"]
    assert first.pending is not None
    assert approval_store.get_pending(tenant_id, first.pending.pending_id) is not None


def test_handle_rejects_cross_tenant_payload_mismatch() -> None:
    request_tenant_id = str(uuid4())
    service = WebhookService(
        SimpleNamespace(process_webhook=lambda *_args, **_kwargs: _response()),
        _DedupStub(),
        _TracerStub(),
        Settings(anthropic_api_key="k"),
    )

    with pytest.raises(AgentError) as exc:
        service.handle(
            WebhookRequest(text="hello", tenant_id=str(uuid4()), message_id="msg-1"),
            _request(request_tenant_id),
        )

    assert exc.value.status_code == 401
    assert exc.value.detail == "Unauthorized"


def test_handle_rejects_missing_tenant_id() -> None:
    service = WebhookService(
        SimpleNamespace(process_webhook=lambda *_args, **_kwargs: _response()),
        _DedupStub(),
        _TracerStub(),
        Settings(anthropic_api_key="k"),
    )

    with pytest.raises(AgentError) as exc:
        service.handle(WebhookRequest(text="hello"), _request())

    assert exc.value.status_code == 400
    assert exc.value.detail == "tenant_id is required"


def test_handle_surfaces_agent_error() -> None:
    tenant_id = str(uuid4())

    def _raise(*_args, **_kwargs):
        raise AgentError("bad agent", status_code=422)

    service = WebhookService(
        SimpleNamespace(process_webhook=_raise),
        _DedupStub(),
        _TracerStub(),
        Settings(anthropic_api_key="k"),
    )

    with pytest.raises(AgentError) as exc:
        service.handle(
            WebhookRequest(text="hello", tenant_id=tenant_id, message_id="msg-1"),
            _request(),
        )

    assert exc.value.status_code == 422
    assert exc.value.detail == "bad agent"


def test_handle_uses_request_tenant_when_payload_has_none() -> None:
    """Request-state tenant_id is used when payload omits tenant_id."""
    request_tenant_id = str(uuid4())
    response = _response()
    calls: list[WebhookRequest] = []

    agent = SimpleNamespace(
        process_webhook=lambda payload, message_id=None: calls.append(payload) or response
    )
    service = WebhookService(agent, _DedupStub(), _TracerStub(), Settings(anthropic_api_key="k"))

    result = service.handle(
        WebhookRequest(text="hello", message_id="msg-r"),
        _request(request_tenant_id),
    )

    assert result == response
    assert calls[0].tenant_id == request_tenant_id


def test_handle_keeps_demo_llm_mode_inside_webhook_boundaries() -> None:
    tenant_id = str(uuid4())
    settings = Settings(
        llm_mode="demo",
        approval_categories=["billing"],
        auto_approve_threshold=0.85,
    )
    agent = AgentService(
        settings=settings,
        store=EventStore(sqlite_path=None),
        approval_store=RedisApprovalStore(fakeredis.FakeRedis(), ttl_seconds=3600),
    )
    dedup = _DedupStub()
    service = WebhookService(agent, dedup, _TracerStub(), settings)

    result = service.handle(
        WebhookRequest(
            text="I was charged twice for the starter pack and need a refund review.",
            tenant_id=tenant_id,
            message_id="sample-risky-01",
            user_id="u1",
        ),
        _request(),
    )

    assert result.status == "pending"
    assert result.classification.category == "billing"
    assert dedup.check_calls == [(tenant_id, "sample-risky-01")]
    assert dedup.set_calls
