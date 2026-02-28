"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request

from app.agent import AgentService
from app.config import get_settings
from app.logging import clear_request_id, configure_logging, set_request_id
from app.schemas import ApproveRequest, ApproveResponse, HealthResponse, WebhookRequest, WebhookResponse
from app.store import EventStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize runtime dependencies on startup."""
    settings = get_settings()
    configure_logging(settings.log_level)
    store = EventStore(sqlite_path=settings.sqlite_log_path)
    app.state.settings = settings
    app.state.agent = AgentService(settings=settings, store=store)
    yield


app = FastAPI(title="gdev-agent", lifespan=lifespan)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Attach a request id to logging context and response headers."""
    request_id = request.headers.get("X-Request-ID") or uuid4().hex
    token = set_request_id(request_id)
    try:
        response = await call_next(request)
    finally:
        clear_request_id(token)
    response.headers["X-Request-ID"] = request_id
    return response


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Service health endpoint."""
    return HealthResponse(app=app.state.settings.app_name)


@app.post("/webhook", response_model=WebhookResponse)
def webhook(payload: WebhookRequest) -> WebhookResponse:
    """Main webhook endpoint used by n8n/Make."""
    try:
        return app.state.agent.process_webhook(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/approve", response_model=ApproveResponse)
def approve(payload: ApproveRequest) -> ApproveResponse:
    """Approve or reject a pending action."""
    return app.state.agent.approve(payload)
