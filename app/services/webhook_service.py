"""Webhook service layer."""

from __future__ import annotations

import hashlib
import logging
from contextlib import nullcontext
from time import perf_counter
from typing import Literal, Protocol
from uuid import UUID, uuid4

from prometheus_client import Counter, Histogram

from app.config import Settings
from app.exceptions import AgentError
from app.logging import REQUEST_ID
from app.schemas import WebhookRequest, WebhookResponse

LOGGER = logging.getLogger(__name__)
WEBHOOK_SERVICE_CALLS_TOTAL = Counter(
    "gdev_webhook_service_calls_total",
    "Webhook service method calls by outcome",
    ["method", "outcome"],
)
WEBHOOK_SERVICE_DURATION_SECONDS = Histogram(
    "gdev_webhook_service_duration_seconds",
    "Webhook service method latency",
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
    def process_webhook(
        self, payload: WebhookRequest, message_id: str | None = None
    ) -> WebhookResponse: ...


class _DedupProtocol(Protocol):
    def check(self, tenant_id: str, message_id: str) -> str | None: ...

    def set(self, tenant_id: str, message_id: str, body: str) -> object: ...


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


class WebhookService:
    """Business logic for webhook processing."""

    def __init__(
        self,
        agent: _AgentProtocol,
        dedup: _DedupProtocol,
        tracer: _TracerProtocol | None,
        settings: Settings,
    ) -> None:
        self._agent = agent
        self._dedup = dedup
        self._tracer = tracer or _NoopTracer()
        self._settings = settings

    def handle(self, payload: WebhookRequest, request) -> WebhookResponse:  # noqa: ANN001
        started_at = perf_counter()
        message_id = payload.message_id or uuid4().hex
        cacheable = payload.message_id is not None
        trace_context = getattr(getattr(request, "state", None), "trace_context", None)

        root_cm = self._tracer.start_as_current_span(
            "http.request", context=trace_context
        )
        with root_cm as root_span:
            root_span.set_attribute("http.method", "POST")
            root_span.set_attribute("http.route", "/webhook")
            root_span.set_attribute("request_id", REQUEST_ID.get() or "")
            root_span.set_attribute("message.cacheable", cacheable)
            try:
                tenant_id = self.resolve_tenant(payload, request)
                root_span.set_attribute("tenant_id_hash", _sha256_short(tenant_id))
                normalized_payload = self.validate_payload(payload, request, tenant_id)
                cached = self.check_dedup(
                    tenant_id=tenant_id,
                    message_id=message_id,
                    cacheable=cacheable,
                )
                if cached is not None:
                    root_span.set_attribute("http.status_code", 200)
                    WEBHOOK_SERVICE_CALLS_TOTAL.labels(
                        method="handle", outcome="dedup_hit"
                    ).inc()
                    LOGGER.info(
                        "webhook dedup hit",
                        extra={
                            "event": "webhook_dedup_hit",
                            "context": {"tenant_id_hash": _sha256_short(tenant_id)},
                        },
                    )
                    return cached

                response = self._agent.process_webhook(
                    normalized_payload, message_id=message_id
                )
                if cacheable:
                    self._dedup.set(tenant_id, message_id, response.model_dump_json())
                root_span.set_attribute("http.status_code", 200)
                WEBHOOK_SERVICE_CALLS_TOTAL.labels(
                    method="handle", outcome="success"
                ).inc()
                LOGGER.info(
                    "webhook handled",
                    extra={
                        "event": "webhook_handled",
                        "context": {"tenant_id_hash": _sha256_short(tenant_id)},
                    },
                )
                return response
            except AgentError as exc:
                root_span.set_attribute("http.status_code", exc.status_code)
                root_span.record_exception(exc)
                WEBHOOK_SERVICE_CALLS_TOTAL.labels(method="handle", outcome="error").inc()
                LOGGER.error(
                    "webhook handling failed",
                    extra={"event": "webhook_handling_failed", "context": {}},
                    exc_info=True,
                )
                raise
            finally:
                WEBHOOK_SERVICE_DURATION_SECONDS.labels(method="handle").observe(
                    perf_counter() - started_at
                )

    def resolve_tenant(self, payload: WebhookRequest, request) -> str:  # noqa: ANN001
        started_at = perf_counter()
        with self._tracer.start_as_current_span("service.webhook.resolve_tenant") as span:
            request_tenant_id = getattr(getattr(request, "state", None), "tenant_id", None)
            resolved_tenant_id = request_tenant_id or payload.tenant_id
            try:
                if not resolved_tenant_id:
                    WEBHOOK_SERVICE_CALLS_TOTAL.labels(
                        method="resolve_tenant", outcome="missing_tenant"
                    ).inc()
                    raise AgentError("tenant_id is required", status_code=400)
                tenant_uuid = UUID(str(resolved_tenant_id))
                tenant_id = str(tenant_uuid)
                span.set_attribute("tenant_id_hash", _sha256_short(tenant_id))
                WEBHOOK_SERVICE_CALLS_TOTAL.labels(
                    method="resolve_tenant", outcome="success"
                ).inc()
                LOGGER.info(
                    "webhook tenant resolved",
                    extra={
                        "event": "webhook_tenant_resolved",
                        "context": {"tenant_id_hash": _sha256_short(tenant_id)},
                    },
                )
                return tenant_id
            except AgentError as exc:
                span.record_exception(exc)
                LOGGER.error(
                    "webhook tenant resolution failed",
                    extra={"event": "webhook_tenant_resolution_failed", "context": {}},
                    exc_info=True,
                )
                raise
            except (TypeError, ValueError) as exc:
                span.record_exception(exc)
                WEBHOOK_SERVICE_CALLS_TOTAL.labels(
                    method="resolve_tenant", outcome="invalid_tenant"
                ).inc()
                LOGGER.error(
                    "webhook tenant invalid",
                    extra={"event": "webhook_tenant_invalid", "context": {}},
                    exc_info=True,
                )
                raise AgentError(
                    "tenant_id must be a valid UUID", status_code=400
                ) from exc
            finally:
                WEBHOOK_SERVICE_DURATION_SECONDS.labels(
                    method="resolve_tenant"
                ).observe(perf_counter() - started_at)

    def validate_payload(
        self, payload: WebhookRequest, request, tenant_id: str  # noqa: ANN001
    ) -> WebhookRequest:
        started_at = perf_counter()
        with self._tracer.start_as_current_span("service.webhook.validate_payload") as span:
            span.set_attribute("tenant_id_hash", _sha256_short(tenant_id))
            request_tenant_id = getattr(getattr(request, "state", None), "tenant_id", None)
            try:
                if (
                    request_tenant_id is not None
                    and payload.tenant_id is not None
                    and payload.tenant_id != str(request_tenant_id)
                ):
                    WEBHOOK_SERVICE_CALLS_TOTAL.labels(
                        method="validate_payload", outcome="tenant_mismatch"
                    ).inc()
                    raise AgentError("Unauthorized", status_code=401)
                validated = payload.model_copy(update={"tenant_id": tenant_id})
                WEBHOOK_SERVICE_CALLS_TOTAL.labels(
                    method="validate_payload", outcome="success"
                ).inc()
                LOGGER.info(
                    "webhook payload validated",
                    extra={
                        "event": "webhook_payload_validated",
                        "context": {"tenant_id_hash": _sha256_short(tenant_id)},
                    },
                )
                return validated
            except AgentError as exc:
                span.record_exception(exc)
                LOGGER.error(
                    "webhook payload validation failed",
                    extra={"event": "webhook_payload_validation_failed", "context": {}},
                    exc_info=True,
                )
                raise
            finally:
                WEBHOOK_SERVICE_DURATION_SECONDS.labels(
                    method="validate_payload"
                ).observe(perf_counter() - started_at)

    def check_dedup(
        self, *, tenant_id: str, message_id: str, cacheable: bool
    ) -> WebhookResponse | None:
        started_at = perf_counter()
        span_cm = (
            self._tracer.start_as_current_span("middleware.dedup")
            if cacheable
            else nullcontext(_NoopSpan())
        )
        with span_cm as span:
            span.set_attribute("cacheable", cacheable)
            span.set_attribute("tenant_id_hash", _sha256_short(tenant_id))
            try:
                if not cacheable:
                    WEBHOOK_SERVICE_CALLS_TOTAL.labels(
                        method="check_dedup", outcome="skip"
                    ).inc()
                    return None
                cached = self._dedup.check(tenant_id, message_id)
                hit = cached is not None
                span.set_attribute("dedup.hit", hit)
                WEBHOOK_SERVICE_CALLS_TOTAL.labels(
                    method="check_dedup", outcome="hit" if hit else "miss"
                ).inc()
                if not hit:
                    return None
                LOGGER.info(
                    "dedup hit",
                    extra={
                        "event": "dedup_hit",
                        "context": {"tenant_id_hash": _sha256_short(tenant_id)},
                    },
                )
                return WebhookResponse.model_validate_json(cached)
            except Exception as exc:
                span.record_exception(exc)
                WEBHOOK_SERVICE_CALLS_TOTAL.labels(
                    method="check_dedup", outcome="error"
                ).inc()
                LOGGER.error(
                    "webhook dedup lookup failed",
                    extra={"event": "webhook_dedup_lookup_failed", "context": {}},
                    exc_info=True,
                )
                raise
            finally:
                WEBHOOK_SERVICE_DURATION_SECONDS.labels(method="check_dedup").observe(
                    perf_counter() - started_at
                )
