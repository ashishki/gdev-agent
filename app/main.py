"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import redis
import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

try:  # pragma: no cover - optional in minimal local envs
    from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - scheduler remains disabled
    AsyncIOScheduler = None  # type: ignore[assignment]

from app.agent import AgentService
from app.approval_store import RedisApprovalStore
from app.config import get_settings
from app.dependencies import require_role
from app.db import make_engine, make_session_factory
from app.dedup import DedupCache
from app.embedding_service import EmbeddingService
from app.exceptions import AgentError
from app.integrations.sheets import SheetsClient
from app.integrations.telegram import TelegramClient
from app.jobs.rca_clusterer import RCAClusterer
from app.logging import clear_request_id, configure_logging, set_request_id
from app.metrics import render_metrics
from app.middleware.auth import JWTMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.signature import SignatureMiddleware
from app.routers.agents import router as agents_router
from app.routers.analytics import router as analytics_router
from app.routers.auth import router as auth_router
from app.routers.clusters import router as clusters_router
from app.routers.eval import router as eval_router
from app.routers.tickets import router as tickets_router
from app.schemas import (
    ApproveRequest,
    ApproveResponse,
    HealthResponse,
    WebhookRequest,
    WebhookResponse,
)
from app.services.approval_service import ApprovalService
from app.services.webhook_service import WebhookService
from app.secrets_store import WebhookSecretStore
from app.store import EventStore
from app.tenant_registry import TenantRegistry

LOGGER = logging.getLogger(__name__)
OTEL_TRACE = None
OTEL_PROPAGATE = None
TRACER: Any = None

try:  # pragma: no cover - optional dependency in minimal local envs
    from opentelemetry import propagate as _otel_propagate  # type: ignore[import-not-found]
    from opentelemetry import trace as _otel_trace  # type: ignore[import-not-found]
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import-not-found]
        OTLPSpanExporter,
    )
    from opentelemetry.sdk.resources import Resource  # type: ignore[import-not-found]
    from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-not-found]
    from opentelemetry.sdk.trace.export import (  # type: ignore[import-not-found]
        BatchSpanProcessor,
        ConsoleSpanExporter,
    )

    OTEL_TRACE = _otel_trace
    OTEL_PROPAGATE = _otel_propagate
except Exception:  # pragma: no cover - tracing remains disabled without dependencies
    OTEL_TRACE = None
    OTEL_PROPAGATE = None


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach request id to logging context and response headers."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid4().hex
        token = set_request_id(request_id)
        try:
            response = await call_next(request)
        finally:
            clear_request_id(token)
        response.headers["X-Request-ID"] = request_id
        return response


def _configure_tracing(settings) -> None:
    global TRACER
    if OTEL_TRACE is None:
        TRACER = None
        return
    resource = Resource.create({"service.name": settings.otel_service_name})
    provider = TracerProvider(resource=resource)
    if settings.otlp_endpoint:
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otlp_endpoint))
        )
    elif settings.app_env == "dev":
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    OTEL_TRACE.set_tracer_provider(provider)
    TRACER = OTEL_TRACE.get_tracer(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize runtime dependencies on startup."""
    settings = get_settings()
    configure_logging(settings.log_level)
    _configure_tracing(settings)
    if settings.webhook_secret:
        LOGGER.warning(
            "legacy webhook secret configured",
            extra={
                "event": "security_degraded",
                "context": {
                    "reason": "WEBHOOK_SECRET is deprecated; use per-tenant encrypted secrets"
                },
            },
        )
    if not settings.approve_secret:
        LOGGER.warning(
            "approve endpoint authentication disabled",
            extra={
                "event": "security_degraded",
                "context": {
                    "reason": "APPROVE_SECRET not set - approve endpoint auth skipped"
                },
            },
        )
    if len(settings.jwt_secret) < 32:
        LOGGER.error(
            "jwt secret too short",
            extra={
                "event": "security_degraded",
                "context": {"reason": "JWT_SECRET is shorter than 32 bytes"},
            },
        )

    redis_client = redis.from_url(settings.redis_url)
    try:
        redis_client.ping()
    except Exception as exc:
        raise RuntimeError("Redis unavailable at startup") from exc

    db_engine = make_engine(settings)
    db_session_factory = make_session_factory(db_engine)
    tenant_registry_redis = aioredis.from_url(settings.redis_url)
    webhook_secret_store = None
    if settings.webhook_secret_encryption_key:
        webhook_secret_store = WebhookSecretStore(
            db_session_factory, settings.webhook_secret_encryption_key
        )

    store = EventStore(
        sqlite_path=settings.sqlite_log_path,
        db_session_factory=db_session_factory,
    )
    embedding_service = EmbeddingService(
        settings=settings, db_session_factory=db_session_factory
    )
    rca_clusterer = RCAClusterer(
        settings=settings,
        db_session_factory=db_session_factory,
    )
    approval_store = RedisApprovalStore(
        redis_client,
        ttl_seconds=settings.approval_ttl_seconds,
        db_session_factory=db_session_factory,
    )
    dedup_cache = DedupCache(redis_client)
    scheduler = None
    if AsyncIOScheduler is not None:
        scheduler = AsyncIOScheduler(timezone="UTC")
        scheduler.add_job(
            rca_clusterer.run_with_timeout, "interval", minutes=15, id="rca_clusterer"
        )
        scheduler.start()

    telegram_client = (
        TelegramClient(settings.telegram_bot_token)
        if settings.telegram_bot_token
        else None
    )
    sheets_client = SheetsClient(
        settings.google_sheets_credentials_json, settings.google_sheets_id
    )

    app.state.settings = settings
    app.state.redis = redis_client
    app.state.db_engine = db_engine
    app.state.db_session_factory = db_session_factory
    app.state.jwt_blocklist_redis = tenant_registry_redis
    app.state.webhook_secret_store = webhook_secret_store
    app.state.tenant_registry = TenantRegistry(
        tenant_registry_redis, db_session_factory
    )
    app.state.dedup = dedup_cache
    app.state.agent = AgentService(
        settings=settings,
        store=store,
        approval_store=approval_store,
        telegram_client=telegram_client,
        sheets_client=sheets_client,
        embedding_service=embedding_service,
    )
    app.state.webhook_service = WebhookService(
        agent=app.state.agent,
        dedup=dedup_cache,
        tracer=TRACER,
        settings=settings,
    )
    app.state.approval_service = ApprovalService(
        agent=app.state.agent,
        settings=settings,
        tracer=TRACER,
    )
    app.state.rca_clusterer = rca_clusterer
    app.state.rca_scheduler = scheduler
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        await rca_clusterer.aclose()
        await tenant_registry_redis.aclose()
        await db_engine.dispose()


app = FastAPI(title="gdev-agent", lifespan=lifespan)


@app.exception_handler(AgentError)
async def handle_agent_error(_request: Request, exc: AgentError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

# Starlette adds latest middleware first, so add reverse of desired runtime order.
app.add_middleware(RequestIDMiddleware)
app.add_middleware(JWTMiddleware)
app.add_middleware(
    RateLimitMiddleware,
    redis_client=None,
)
app.add_middleware(SignatureMiddleware)
app.include_router(auth_router)
app.include_router(tickets_router)
app.include_router(clusters_router)
app.include_router(analytics_router)
app.include_router(agents_router)
app.include_router(eval_router)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Service health endpoint."""
    return HealthResponse(app=app.state.settings.app_name)


def _get_webhook_service() -> WebhookService:
    settings = getattr(app.state, "settings", None)
    if settings is None:
        settings = getattr(getattr(app.state, "agent", None), "settings", None)
    if settings is None:
        settings = get_settings()
    return getattr(
        app.state,
        "webhook_service",
        WebhookService(
            agent=app.state.agent,
            dedup=app.state.dedup,
            tracer=TRACER,
            settings=settings,
        ),
    )


def _get_approval_service() -> ApprovalService:
    settings = getattr(app.state, "settings", None)
    if settings is None:
        settings = getattr(getattr(app.state, "agent", None), "settings", None)
    if settings is None:
        settings = get_settings()
    return getattr(
        app.state,
        "approval_service",
        ApprovalService(
            agent=app.state.agent,
            settings=settings,
            tracer=TRACER,
        ),
    )


@app.post("/webhook", response_model=WebhookResponse)
def webhook(payload: WebhookRequest, request: Request) -> WebhookResponse:
    """Main webhook endpoint used by n8n/Make."""
    if OTEL_PROPAGATE is not None:
        request.state.trace_context = OTEL_PROPAGATE.extract(dict(request.headers))
    return _get_webhook_service().handle(payload, request)


@app.post("/approve", response_model=ApproveResponse)
def approve(
    payload: ApproveRequest,
    request: Request,
    _: None = require_role("support_agent", "tenant_admin"),
) -> ApproveResponse:
    """Approve or reject a pending action."""
    request_state = getattr(request, "state", None)
    jwt_tenant_id = (
        str(request_state.tenant_id)
        if getattr(request_state, "tenant_id", None)
        else None
    )
    return _get_approval_service().handle(
        payload,
        jwt_tenant_id=jwt_tenant_id,
        approve_secret_header=request.headers.get("X-Approve-Secret"),
    )


@app.get("/metrics")
def metrics() -> Response:
    # JWT auth is intentionally exempted for Prometheus scrapes; access is restricted at the network layer.
    return Response(content=render_metrics(), media_type="text/plain; version=0.0.4")
