"""Core agent decision logic for request triage."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException

from app.approval_store import RedisApprovalStore
from app.config import Settings
from app.guardrails.output_guard import OutputGuard
from app.integrations.sheets import SheetsClient
from app.integrations.telegram import TelegramClient
from app.llm_client import LLMClient
from app.logging import REQUEST_ID
from app.schemas import (
    ApproveRequest,
    ApproveResponse,
    AuditLogEntry,
    ClassificationResult,
    ExtractedFields,
    PendingDecision,
    ProposedAction,
    WebhookRequest,
    WebhookResponse,
)
from app.store import EventStore
from app.tools import TOOL_REGISTRY

LOGGER = logging.getLogger(__name__)

INJECTION_PATTERNS = (
    "ignore previous instructions",
    "system:",
    "[inst]",
    "[/inst]",
    "act as",
    "you are now",
    "forget all",
    "disregard",
    "developer mode",
    "jailbreak",
    "bypass",
    "pretend you",
    "<|system|>",
    "[system]",
    "###instruction",
)


class AgentService:
    """Coordinates classification, extraction, and action execution."""

    def __init__(
        self,
        settings: Settings,
        store: EventStore,
        approval_store: RedisApprovalStore,
        llm_client: LLMClient | None = None,
        output_guard: OutputGuard | None = None,
        telegram_client: TelegramClient | None = None,
        sheets_client: SheetsClient | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.approval_store = approval_store
        self.llm_client = llm_client or LLMClient(settings)
        self.output_guard = output_guard or OutputGuard(settings)
        self.telegram_client = telegram_client
        self.sheets_client = sheets_client

    def process_webhook(self, payload: WebhookRequest, message_id: str | None = None) -> WebhookResponse:
        """Run the full agent flow and return either executed or pending result."""
        start = time.monotonic()
        self._guard_input(payload.text)

        triage = self.llm_client.run_agent(payload.text, payload.user_id)
        classification = triage.classification
        extracted = triage.extracted
        action, draft_response = self.propose_action(payload, classification, extracted)

        guard_result = self.output_guard.scan(draft_response, classification.confidence, action)
        if guard_result.blocked:
            raise HTTPException(status_code=500, detail="Internal: output guard blocked response")
        if guard_result.redacted_draft != draft_response:
            LOGGER.info(
                "output redacted",
                extra={
                    "event": "output_guard_redacted",
                    "context": {"request_id": REQUEST_ID.get()},
                },
            )
        draft_response = guard_result.redacted_draft

        if self.needs_approval(payload.text, classification, action):
            pending = PendingDecision(
                pending_id=uuid4().hex,
                reason=action.risk_reason or "manual approval required",
                user_id=payload.user_id,
                expires_at=datetime.now(UTC) + timedelta(seconds=self.settings.approval_ttl_seconds),
                action=action,
                draft_response=draft_response,
            )
            self.approval_store.put_pending(pending)
            self.store.log_event("pending_created", pending.model_dump(mode="json"))
            self._notify_approval_channel(pending, classification)
            latency_ms = round((time.monotonic() - start) * 1000)
            LOGGER.info(
                "action pending approval",
                extra={
                    "event": "pending_action",
                    "context": {
                        "category": classification.category,
                        "urgency": classification.urgency,
                        "confidence": classification.confidence,
                        "latency_ms": latency_ms,
                        "pending_id": pending.pending_id,
                    },
                },
            )
            return WebhookResponse(
                status="pending",
                classification=classification,
                extracted=extracted,
                action=action,
                draft_response=draft_response,
                pending=pending,
            )

        action_result = self.execute_action(action, payload.user_id, draft_response)
        latency_ms = round((time.monotonic() - start) * 1000)
        LOGGER.info(
            "action executed",
            extra={
                "event": "action_executed",
                "context": {
                    "category": classification.category,
                    "urgency": classification.urgency,
                    "confidence": classification.confidence,
                    "latency_ms": latency_ms,
                    "pending_id": None,
                },
            },
        )

        self._append_audit_async(
            AuditLogEntry(
                timestamp=datetime.now(UTC).isoformat(),
                request_id=REQUEST_ID.get(),
                message_id=message_id,
                user_id=hashlib.sha256(payload.user_id.encode()).hexdigest() if payload.user_id else None,
                category=classification.category,
                urgency=classification.urgency,
                confidence=classification.confidence,
                action=action.tool,
                status="executed",
                approved_by="auto",
                ticket_id=str(action_result.get("ticket", {}).get("ticket_id", "")),
                latency_ms=latency_ms,
                cost_usd=0.0,
            )
        )

        return WebhookResponse(
            status="executed",
            classification=classification,
            extracted=extracted,
            action=action,
            draft_response=draft_response,
            action_result=action_result,
        )

    def approve(self, request: ApproveRequest) -> ApproveResponse:
        """Approve or reject a pending action."""
        pending = self.approval_store.pop_pending(request.pending_id)
        if not pending:
            raise HTTPException(status_code=404, detail="pending_id not found")

        if not request.approved:
            self.store.log_event(
                "pending_rejected",
                {"pending_id": request.pending_id, "reviewer": request.reviewer},
            )
            return ApproveResponse(status="rejected", pending_id=request.pending_id)

        started = time.monotonic()
        result = self.execute_action(pending.action, pending.user_id, pending.draft_response)
        latency_ms = round((time.monotonic() - started) * 1000)
        self.store.log_event(
            "pending_approved",
            {"pending_id": request.pending_id, "reviewer": request.reviewer, "result": result},
        )
        self._append_audit_async(
            AuditLogEntry(
                timestamp=datetime.now(UTC).isoformat(),
                request_id=REQUEST_ID.get(),
                message_id=None,
                user_id=hashlib.sha256(pending.user_id.encode()).hexdigest() if pending.user_id else None,
                category=str(pending.action.payload.get("category", "other")),
                urgency=str(pending.action.payload.get("urgency", "low")),
                confidence=0.0,
                action=pending.action.tool,
                status="approved",
                approved_by=request.reviewer,
                ticket_id=str(result.get("ticket", {}).get("ticket_id", "")),
                latency_ms=latency_ms,
                cost_usd=0.0,
            )
        )
        return ApproveResponse(status="approved", pending_id=request.pending_id, result=result)

    def propose_action(
        self,
        payload: WebhookRequest,
        classification: ClassificationResult,
        extracted: ExtractedFields,
    ) -> tuple[ProposedAction, str]:
        """Build next action and user-facing draft response."""
        title = f"[{classification.category}] support request"
        draft = self._draft_response(classification)

        risky = False
        reason = None
        if classification.category in self.settings.approval_categories:
            risky = True
            reason = f"category '{classification.category}' requires approval"
        if classification.urgency in {"high", "critical"}:
            risky = True
            reason = reason or f"urgency '{classification.urgency}' requires approval"
        if classification.confidence < self.settings.auto_approve_threshold:
            risky = True
            reason = reason or "low confidence classification"
        lowered = payload.text.lower()
        if any(token in lowered for token in ("lawyer", "lawsuit", "press", "gdpr")):
            risky = True
            reason = reason or "legal-risk keywords require approval"

        action = ProposedAction(
            tool="create_ticket_and_reply",
            payload={
                "title": title,
                "text": payload.text,
                "category": classification.category,
                "urgency": classification.urgency,
                "transaction_id": extracted.transaction_id,
                "reply_to": payload.metadata.get("chat_id") or payload.user_id,
            },
            risky=risky,
            risk_reason=reason,
        )
        return action, draft

    def needs_approval(self, text: str, classification: ClassificationResult, action: ProposedAction) -> bool:
        """Determine if action must go through manual approval."""
        _ = (text, classification)
        return action.risky

    def execute_action(self, action: ProposedAction, user_id: str | None, draft_response: str) -> dict[str, object]:
        """Execute tool handlers from the tool registry."""
        handler = TOOL_REGISTRY.get(action.tool)
        if handler is None:
            raise ValueError(f"Unknown tool: {action.tool!r}")

        payload = dict(action.payload)
        payload["draft_response"] = draft_response
        result = handler(payload, user_id)
        self.store.log_event("action_executed", result)
        return result

    def _guard_input(self, text: str) -> None:
        """Validate incoming text and raise ValueError on guardrail hit."""
        if len(text) > self.settings.max_input_length:
            raise ValueError(f"Input exceeds max length ({self.settings.max_input_length})")
        lowered = text.lower()
        if any(pattern in lowered for pattern in INJECTION_PATTERNS):
            raise ValueError("Input failed injection guard")

    def _draft_response(self, classification: ClassificationResult) -> str:
        """Generate a short user-facing draft reply."""
        if classification.category == "billing":
            return "Thanks for reporting this payment issue. We are reviewing it and will update you shortly."
        if classification.category == "account_access":
            return "We received your account access request and escalated it to support for urgent review."
        if classification.category == "bug_report":
            return "Thanks for the bug report. We have shared it with the team and will follow up with steps."
        if classification.category == "cheater_report":
            return "Thanks for the report. Our moderation team will investigate this player activity."
        if classification.category == "gameplay_question":
            return "Thanks for your question. We will send the best available guidance shortly."
        return "Thanks for contacting support. We have logged your request and will reply soon."

    def _notify_approval_channel(self, pending: PendingDecision, classification: ClassificationResult) -> None:
        """Send pending approval notification to Telegram approval chat."""
        if not self.telegram_client or not self.settings.telegram_approval_chat_id:
            return
        try:
            self.telegram_client.send_approval_request(
                chat_id=self.settings.telegram_approval_chat_id,
                pending_id=pending.pending_id,
                draft=pending.draft_response,
                category=classification.category,
                urgency=classification.urgency,
                reason=pending.reason,
            )
        except Exception:
            LOGGER.warning(
                "failed sending approval notification",
                extra={"event": "approval_notify_failed", "context": {"pending_id": pending.pending_id}},
            )

    def _append_audit_async(self, entry: AuditLogEntry) -> None:
        """Write audit logs without blocking request completion."""
        if not self.sheets_client:
            return
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.run_in_executor(None, self.sheets_client.append_log, entry)
                return
        except RuntimeError:
            pass
        threading.Thread(target=self.sheets_client.append_log, args=(entry,), daemon=True).start()
