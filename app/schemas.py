"""Pydantic schemas for API and internal agent I/O."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

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
    tenant_id: str | None = None
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
    tenant_id: str
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


class AuthTokenRequest(BaseModel):
    """Credentials payload for POST /auth/token."""

    tenant_slug: str = Field(..., min_length=1)
    email: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class AuthTokenResponse(BaseModel):
    """Token response payload for POST /auth/token."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class HealthResponse(BaseModel):
    """Healthcheck response model."""

    status: Literal["ok"] = "ok"
    app: str


class AuditLogEntry(BaseModel):
    """Audit entry persisted to Google Sheets."""

    timestamp: str
    request_id: str | None = None
    tenant_id: str | None = None
    message_id: str | None = None
    user_id: str | None = None
    category: str
    urgency: str
    confidence: float
    action: str
    status: str
    approved_by: str | None = None
    ticket_id: str | None = None
    latency_ms: int
    cost_usd: float = 0.0


class ErrorDetail(BaseModel):
    """Standard API error payload."""

    code: str
    message: str


class ErrorResponse(BaseModel):
    """Error response envelope."""

    error: ErrorDetail


class TicketListItem(BaseModel):
    """Ticket list row."""

    ticket_id: UUID
    message_id: str | None = None
    platform: str | None = None
    game_title: str | None = None
    created_at: datetime


class TicketDetailItem(BaseModel):
    """Single ticket detail row."""

    ticket_id: UUID
    message_id: str | None = None
    platform: str | None = None
    game_title: str | None = None
    raw_text: str
    created_at: datetime
    category: str | None = None
    urgency: str | None = None
    confidence: Decimal | None = None
    action_tool: str | None = None
    status: str | None = None


class AuditListItem(BaseModel):
    """Audit log row."""

    audit_id: UUID
    request_id: str | None = None
    message_id: str | None = None
    category: str | None = None
    urgency: str | None = None
    confidence: Decimal | None = None
    action_tool: str | None = None
    status: str | None = None
    ticket_id: UUID | None = None
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: Decimal | None = None
    created_at: datetime


class CostMetricItem(BaseModel):
    """Cost ledger row."""

    ledger_id: UUID
    date: date
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    request_count: int
    created_at: datetime


class AgentConfigItem(BaseModel):
    """Agent config row."""

    agent_config_id: UUID
    agent_name: str
    version: int
    model_id: str
    max_turns: int
    tools_enabled: list[str]
    guardrails: dict[str, Any]
    prompt_version: str
    is_current: bool
    created_at: datetime


class AgentConfigUpdate(BaseModel):
    """Agent config update payload for PUT /agents/{agent_id}."""

    agent_name: str = Field(..., min_length=1)
    model_id: str = Field(..., min_length=1)
    max_turns: int = Field(..., ge=1)
    tools_enabled: list[str]
    guardrails: dict[str, Any]
    prompt_version: str = Field(..., min_length=1)


class EvalRunItem(BaseModel):
    """Eval run row."""

    eval_run_id: UUID
    started_at: datetime | None = None
    completed_at: datetime | None = None
    f1_score: Decimal | None = None
    guard_block_rate: Decimal | None = None
    cost_usd: Decimal | None = None
    status: str
    created_at: datetime


class ClusterListItem(BaseModel):
    """Cluster summary row."""

    cluster_id: UUID
    label: str
    summary: str
    ticket_count: int
    severity: str | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    is_active: bool
    updated_at: datetime


class ClusterDetailItem(BaseModel):
    """Cluster detail row including ticket members."""

    cluster_id: UUID
    label: str
    summary: str
    ticket_count: int
    severity: str | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    is_active: bool
    updated_at: datetime
    ticket_ids: list[UUID] = Field(default_factory=list)


class TicketListResponse(BaseModel):
    """Envelope for ticket list responses."""

    data: list[TicketListItem]
    cursor: str | None = None
    total: None = None


class TicketDetailResponse(BaseModel):
    """Envelope for ticket detail responses."""

    data: list[TicketDetailItem]
    cursor: str | None = None
    total: None = None


class AuditListResponse(BaseModel):
    """Envelope for audit list responses."""

    data: list[AuditListItem]
    cursor: str | None = None
    total: None = None


class CostMetricResponse(BaseModel):
    """Envelope for cost metric list responses."""

    data: list[CostMetricItem]
    cursor: str | None = None
    total: None = None


class AgentListResponse(BaseModel):
    """Envelope for agent config list responses."""

    data: list[AgentConfigItem]
    cursor: str | None = None
    total: None = None


class EvalRunListResponse(BaseModel):
    """Envelope for eval run list responses."""

    data: list[EvalRunItem]
    cursor: str | None = None
    total: None = None


class ClusterListResponse(BaseModel):
    """Envelope for cluster list responses."""

    data: list[ClusterListItem]
    cursor: str | None = None
    total: None = None


class ClusterDetailResponse(BaseModel):
    """Envelope for cluster detail responses."""

    data: list[ClusterDetailItem]
    cursor: str | None = None
    total: None = None
