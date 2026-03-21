"""Unit tests for the webhook service layer."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.config import Settings
from app.exceptions import AgentError
from app.schemas import (
    ClassificationResult,
    ExtractedFields,
    ProposedAction,
    WebhookRequest,
    WebhookResponse,
)
from app.services.webhook_service import WebhookService


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


def _response() -> WebhookResponse:
    return WebhookResponse(
        status="executed",
        classification=ClassificationResult(
            category="other", urgency="low", confidence=0.9
        ),
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
        process_webhook=lambda payload, message_id=None: calls.append(
            (payload, message_id)
        )
        or response
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
