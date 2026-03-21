"""Unit tests for the approval service layer."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.config import Settings
from app.exceptions import AgentError
from app.schemas import ApproveRequest, ApproveResponse
from app.services.approval_service import ApprovalService


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


def test_handle_successful_approve() -> None:
    tenant_id = str(uuid4())
    expected = ApproveResponse(status="approved", pending_id="p1", result={"ok": True})
    calls: list[tuple[ApproveRequest, str | None]] = []
    service = ApprovalService(
        agent=SimpleNamespace(
            approve=lambda payload, jwt_tenant_id=None: (
                calls.append((payload, jwt_tenant_id)) or expected
            )
        ),
        settings=Settings(anthropic_api_key="k", approve_secret="secret"),
        tracer=_TracerStub(),
    )

    result = service.handle(
        ApproveRequest(pending_id="p1", approved=True),
        jwt_tenant_id=tenant_id,
        approve_secret_header="secret",
    )

    assert result == expected
    assert calls == [(ApproveRequest(pending_id="p1", approved=True), tenant_id)]


def test_handle_rejects_wrong_approve_secret() -> None:
    service = ApprovalService(
        agent=SimpleNamespace(approve=lambda *_args, **_kwargs: pytest.fail("agent called")),
        settings=Settings(anthropic_api_key="k", approve_secret="secret"),
        tracer=_TracerStub(),
    )

    with pytest.raises(AgentError) as exc:
        service.handle(
            ApproveRequest(pending_id="p1", approved=True),
            jwt_tenant_id=str(uuid4()),
            approve_secret_header="wrong",
        )

    assert exc.value.status_code == 401
    assert exc.value.detail == "Unauthorized"


def test_handle_surfaces_cross_tenant_approve_not_found() -> None:
    service = ApprovalService(
        agent=SimpleNamespace(
            approve=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AgentError("pending_id not found", status_code=404)
            )
        ),
        settings=Settings(anthropic_api_key="k", approve_secret="secret"),
        tracer=_TracerStub(),
    )

    with pytest.raises(AgentError) as exc:
        service.handle(
            ApproveRequest(pending_id="p1", approved=True),
            jwt_tenant_id=str(uuid4()),
            approve_secret_header="secret",
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "pending_id not found"
