"""FastAPI application entrypoint."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from app.agent import AgentService
from app.config import get_settings
from app.logging import configure_logging
from app.schemas import ApproveRequest, ApproveResponse, HealthResponse, WebhookRequest, WebhookResponse
from app.store import EventStore

settings = get_settings()
configure_logging(settings.log_level)

store = EventStore(sqlite_path=settings.sqlite_log_path)
agent = AgentService(settings=settings, store=store)

app = FastAPI(title=settings.app_name)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Service health endpoint."""
    return HealthResponse(app=settings.app_name)


@app.post("/webhook", response_model=WebhookResponse)
def webhook(payload: WebhookRequest) -> WebhookResponse:
    """Main webhook endpoint used by n8n/Make."""
    try:
        return agent.process_webhook(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/approve", response_model=ApproveResponse)
def approve(payload: ApproveRequest) -> ApproveResponse:
    """Approve or reject a pending action."""
    return agent.approve(payload)
