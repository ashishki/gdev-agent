"""FastAPI application entrypoint."""

from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from uuid import uuid4

import redis
import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.agent import AgentService
from app.approval_store import RedisApprovalStore
from app.config import Settings, get_settings
from app.db import make_engine, make_session_factory
from app.dedup import DedupCache
from app.integrations.sheets import SheetsClient
from app.integrations.telegram import TelegramClient
from app.logging import clear_request_id, configure_logging, set_request_id
from app.middleware.auth import JWTMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.signature import SignatureMiddleware
from app.routers.auth import router as auth_router
from app.schemas import ApproveRequest, ApproveResponse, HealthResponse, WebhookRequest, WebhookResponse
from app.secrets_store import WebhookSecretStore
from app.store import EventStore
from app.tenant_registry import TenantRegistry

LOGGER = logging.getLogger(__name__)


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize runtime dependencies on startup."""
    settings = get_settings()
    configure_logging(settings.log_level)
    if settings.webhook_secret:
        LOGGER.warning(
            "legacy webhook secret configured",
            extra={
                "event": "security_degraded",
                "context": {"reason": "WEBHOOK_SECRET is deprecated; use per-tenant encrypted secrets"},
            },
        )
    if not settings.approve_secret:
        LOGGER.warning(
            "approve endpoint authentication disabled",
            extra={
                "event": "security_degraded",
                "context": {"reason": "APPROVE_SECRET not set - approve endpoint auth skipped"},
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
        webhook_secret_store = WebhookSecretStore(db_session_factory, settings.webhook_secret_encryption_key)

    store = EventStore(sqlite_path=settings.sqlite_log_path)
    approval_store = RedisApprovalStore(redis_client, ttl_seconds=settings.approval_ttl_seconds)
    dedup_cache = DedupCache(redis_client)

    telegram_client = TelegramClient(settings.telegram_bot_token) if settings.telegram_bot_token else None
    sheets_client = SheetsClient(settings.google_sheets_credentials_json, settings.google_sheets_id)

    app.state.settings = settings
    app.state.redis = redis_client
    app.state.db_engine = db_engine
    app.state.db_session_factory = db_session_factory
    app.state.jwt_blocklist_redis = tenant_registry_redis
    app.state.webhook_secret_store = webhook_secret_store
    app.state.tenant_registry = TenantRegistry(tenant_registry_redis, db_session_factory)
    app.state.dedup = dedup_cache
    app.state.agent = AgentService(
        settings=settings,
        store=store,
        approval_store=approval_store,
        telegram_client=telegram_client,
        sheets_client=sheets_client,
    )
    try:
        yield
    finally:
        await tenant_registry_redis.aclose()
        await db_engine.dispose()


app = FastAPI(title="gdev-agent", lifespan=lifespan)
_middleware_settings = Settings()

# Starlette adds latest middleware first, so add reverse of desired runtime order.
app.add_middleware(RequestIDMiddleware)
app.add_middleware(JWTMiddleware, settings=_middleware_settings)
app.add_middleware(
    RateLimitMiddleware,
    settings=_middleware_settings,
    redis_client=redis.from_url(_middleware_settings.redis_url),
)
app.add_middleware(SignatureMiddleware, settings=_middleware_settings)
app.include_router(auth_router)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Service health endpoint."""
    return HealthResponse(app=app.state.settings.app_name)


@app.post("/webhook", response_model=WebhookResponse)
def webhook(payload: WebhookRequest) -> WebhookResponse:
    """Main webhook endpoint used by n8n/Make."""
    message_id = payload.message_id or uuid4().hex
    cacheable = payload.message_id is not None

    if cacheable:
        cached = app.state.dedup.check(message_id)
        if cached is not None:
            LOGGER.info(
                "dedup hit",
                extra={"event": "dedup_hit", "context": {"message_id": message_id}},
            )
            return WebhookResponse.model_validate_json(cached)

    try:
        response = app.state.agent.process_webhook(payload, message_id=message_id)
    except ValueError as exc:
        if str(exc).startswith("Input "):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        raise

    if cacheable:
        app.state.dedup.set(message_id, response.model_dump_json())
    return response


@app.post("/approve", response_model=ApproveResponse)
def approve(payload: ApproveRequest, request: Request) -> ApproveResponse:
    """Approve or reject a pending action."""
    provided = request.headers.get("X-Approve-Secret", "")
    if app.state.settings.approve_secret and not hmac.compare_digest(app.state.settings.approve_secret, provided):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return app.state.agent.approve(payload)
