"""Pydantic schemas for API and internal agent I/O."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Category = Literal[
    "bug_report",
    "billing",
    "account_access",
    "cheater_report",
    "gameplay_question",
    "other",
]
Urgency = Literal["low", "medium", "high", "critical"]


class WebhookRequest(BaseModel):
    """Incoming webhook payload from n8n/Make."""

    request_id: str | None = None
    message_id: str | None = None
    user_id: str | None = None
    text: str = Field(..., min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClassificationResult(BaseModel):
    """Result of request classification."""

    category: Category
    urgency: Urgency
    confidence: float = Field(..., ge=0.0, le=1.0)


class ExtractedFields(BaseModel):
    """Structured fields extracted from free-form text."""

    user_id: str | None = None
    platform: str = "unknown"
    game_title: str | None = None
    transaction_id: str | None = None
    error_code: str | None = None
    reported_username: str | None = None
    keywords: list[str] = Field(default_factory=list)


class ProposedAction(BaseModel):
    """Action proposed by the agent before execution."""

    tool: str
    payload: dict[str, Any]
    risky: bool = False
    risk_reason: str | None = None


class PendingDecision(BaseModel):
    """Pending action requiring human approval."""

    pending_id: str
    reason: str
    user_id: str | None = None
    expires_at: datetime
    action: ProposedAction
    draft_response: str


class WebhookResponse(BaseModel):
    """Response returned by POST /webhook."""

    status: Literal["executed", "pending"]
    classification: ClassificationResult
    extracted: ExtractedFields
    action: ProposedAction
    draft_response: str
    action_result: dict[str, Any] | None = None
    pending: PendingDecision | None = None


class ApproveRequest(BaseModel):
    """Approval payload for POST /approve."""

    pending_id: str
    approved: bool = True
    reviewer: str | None = None


class ApproveResponse(BaseModel):
    """Result payload for POST /approve."""

    status: Literal["approved", "rejected"]
    pending_id: str
    result: dict[str, Any] | None = None


class HealthResponse(BaseModel):
    """Healthcheck response model."""

    status: Literal["ok"] = "ok"
    app: str
