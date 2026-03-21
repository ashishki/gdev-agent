"""Approval service layer."""

from __future__ import annotations

import hashlib
import hmac
import logging
from time import perf_counter
from typing import Literal, Protocol

from prometheus_client import Counter, Histogram

from app.config import Settings
from app.exceptions import AgentError
from app.schemas import ApproveRequest, ApproveResponse

LOGGER = logging.getLogger(__name__)
APPROVAL_SERVICE_CALLS_TOTAL = Counter(
    "gdev_approval_service_calls_total",
    "Approval service method calls by outcome",
    ["method", "outcome"],
)
APPROVAL_SERVICE_DURATION_SECONDS = Histogram(
    "gdev_approval_service_duration_seconds",
    "Approval service method latency",
    ["method"],
)


class _SpanProtocol(Protocol):
    def __enter__(self) -> "_SpanProtocol": ...

    def __exit__(self, exc_type, exc, tb) -> Literal[False]: ...  # noqa: ANN001

    def set_attribute(self, name: str, value: object) -> None: ...

    def record_exception(self, exc: BaseException) -> None: ...


class _TracerProtocol(Protocol):
    def start_as_current_span(
        self, name: str, **kwargs: object
    ) -> _SpanProtocol: ...


class _AgentProtocol(Protocol):
    def approve(
        self, request: ApproveRequest, jwt_tenant_id: str | None = None
    ) -> ApproveResponse: ...


class _NoopSpan:
    def __enter__(self) -> "_NoopSpan":
        return self

    def __exit__(self, exc_type, exc, tb) -> Literal[False]:  # noqa: ANN001
        return False

    def set_attribute(self, _name: str, _value: object) -> None:
        return None

    def record_exception(self, _exc: BaseException) -> None:
        return None


class _NoopTracer:
    def start_as_current_span(self, _name: str, **_kwargs: object) -> _NoopSpan:
        return _NoopSpan()


def _sha256_short(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


class ApprovalService:
    """Business logic for approval endpoint."""

    def __init__(
        self, agent: _AgentProtocol, settings: Settings, tracer: _TracerProtocol | None = None
    ) -> None:
        self._agent = agent
        self._settings = settings
        self._tracer = tracer or _NoopTracer()

    def handle(
        self,
        payload: ApproveRequest,
        jwt_tenant_id: str | None,
        approve_secret_header: str | None,
    ) -> ApproveResponse:
        started_at = perf_counter()
        tenant_id = self.get_tenant(jwt_tenant_id)
        with self._tracer.start_as_current_span("service.approval.handle") as span:
            if tenant_id is not None:
                span.set_attribute("tenant_id_hash", _sha256_short(tenant_id))
            try:
                self.verify_hmac(approve_secret_header, tenant_id=tenant_id)
                response = self.dispatch_approve(payload, tenant_id)
                APPROVAL_SERVICE_CALLS_TOTAL.labels(
                    method="handle", outcome="success"
                ).inc()
                LOGGER.info(
                    "approval handled",
                    extra={
                        "event": "approval_handled",
                        "context": (
                            {"tenant_id_hash": _sha256_short(tenant_id)}
                            if tenant_id is not None
                            else {}
                        ),
                    },
                )
                return response
            except AgentError as exc:
                span.record_exception(exc)
                APPROVAL_SERVICE_CALLS_TOTAL.labels(method="handle", outcome="error").inc()
                LOGGER.error(
                    "approval handling failed",
                    extra={"event": "approval_handling_failed", "context": {}},
                    exc_info=True,
                )
                raise
            finally:
                APPROVAL_SERVICE_DURATION_SECONDS.labels(method="handle").observe(
                    perf_counter() - started_at
                )

    def verify_hmac(
        self, approve_secret_header: str | None, *, tenant_id: str | None
    ) -> None:
        started_at = perf_counter()
        with self._tracer.start_as_current_span("service.approval.verify_hmac") as span:
            if tenant_id is not None:
                span.set_attribute("tenant_id_hash", _sha256_short(tenant_id))
            try:
                if self._settings.approve_secret and not hmac.compare_digest(
                    self._settings.approve_secret, approve_secret_header or ""
                ):
                    APPROVAL_SERVICE_CALLS_TOTAL.labels(
                        method="verify_hmac", outcome="unauthorized"
                    ).inc()
                    raise AgentError("Unauthorized", status_code=401)
                APPROVAL_SERVICE_CALLS_TOTAL.labels(
                    method="verify_hmac", outcome="success"
                ).inc()
                LOGGER.info(
                    "approval secret verified",
                    extra={
                        "event": "approval_secret_verified",
                        "context": (
                            {"tenant_id_hash": _sha256_short(tenant_id)}
                            if tenant_id is not None
                            else {}
                        ),
                    },
                )
            except AgentError as exc:
                span.record_exception(exc)
                LOGGER.error(
                    "approval secret verification failed",
                    extra={"event": "approval_secret_verification_failed", "context": {}},
                    exc_info=True,
                )
                raise
            finally:
                APPROVAL_SERVICE_DURATION_SECONDS.labels(method="verify_hmac").observe(
                    perf_counter() - started_at
                )

    def get_tenant(self, jwt_tenant_id: str | None) -> str | None:
        started_at = perf_counter()
        with self._tracer.start_as_current_span("service.approval.get_tenant") as span:
            if jwt_tenant_id is not None:
                span.set_attribute("tenant_id_hash", _sha256_short(jwt_tenant_id))
            APPROVAL_SERVICE_CALLS_TOTAL.labels(method="get_tenant", outcome="success").inc()
            LOGGER.info(
                "approval tenant resolved",
                extra={
                    "event": "approval_tenant_resolved",
                    "context": (
                        {"tenant_id_hash": _sha256_short(jwt_tenant_id)}
                        if jwt_tenant_id is not None
                        else {}
                    ),
                },
            )
            APPROVAL_SERVICE_DURATION_SECONDS.labels(method="get_tenant").observe(
                perf_counter() - started_at
            )
            return jwt_tenant_id

    def dispatch_approve(
        self, payload: ApproveRequest, tenant_id: str | None
    ) -> ApproveResponse:
        started_at = perf_counter()
        with self._tracer.start_as_current_span("service.approval.dispatch_approve") as span:
            if tenant_id is not None:
                span.set_attribute("tenant_id_hash", _sha256_short(tenant_id))
            try:
                response = self._agent.approve(payload, jwt_tenant_id=tenant_id)
                APPROVAL_SERVICE_CALLS_TOTAL.labels(
                    method="dispatch_approve", outcome="success"
                ).inc()
                LOGGER.info(
                    "approval dispatched",
                    extra={
                        "event": "approval_dispatched",
                        "context": (
                            {"tenant_id_hash": _sha256_short(tenant_id)}
                            if tenant_id is not None
                            else {}
                        ),
                    },
                )
                return response
            except AgentError as exc:
                span.record_exception(exc)
                APPROVAL_SERVICE_CALLS_TOTAL.labels(
                    method="dispatch_approve", outcome="error"
                ).inc()
                LOGGER.error(
                    "approval dispatch failed",
                    extra={"event": "approval_dispatch_failed", "context": {}},
                    exc_info=True,
                )
                raise
            finally:
                APPROVAL_SERVICE_DURATION_SECONDS.labels(
                    method="dispatch_approve"
                ).observe(perf_counter() - started_at)
