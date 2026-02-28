"""Core agent decision logic for request triage."""

from __future__ import annotations

import logging
import re
from uuid import uuid4

from app.config import Settings
from app.schemas import (
    ApproveRequest,
    ApproveResponse,
    ClassificationResult,
    ExtractedFields,
    PendingDecision,
    ProposedAction,
    WebhookRequest,
    WebhookResponse,
)
from app.store import EventStore
from app.tools.messenger import send_reply
from app.tools.ticketing import create_ticket

LOGGER = logging.getLogger(__name__)

INJECTION_PATTERNS = (
    "ignore previous instructions",
    "system:",
    "[inst]",
    "[/inst]",
)


class AgentService:
    """Coordinates classification, extraction, and action execution."""

    def __init__(self, settings: Settings, store: EventStore) -> None:
        self.settings = settings
        self.store = store

    def process_webhook(self, payload: WebhookRequest) -> WebhookResponse:
        """Run the full agent flow and return either executed or pending result."""
        self._guard_input(payload.text)

        classification = self.classify_request(payload.text)
        extracted = self.extract_fields(payload)
        action, draft_response = self.propose_action(payload, classification, extracted)

        if self.needs_approval(payload.text, classification, action):
            pending = PendingDecision(
                pending_id=uuid4().hex,
                reason=action.risk_reason or "manual approval required",
                action=action,
                draft_response=draft_response,
            )
            self.store.put_pending(pending)
            LOGGER.info(
                "action pending approval",
                extra={"event": "pending_action", "context": {"pending_id": pending.pending_id}},
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
        LOGGER.info("action executed", extra={"event": "action_executed", "context": action_result})
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
        pending = self.store.pop_pending(request.pending_id)
        if not pending:
            return ApproveResponse(status="not_found", pending_id=request.pending_id)

        if not request.approved:
            self.store.log_event(
                "pending_rejected",
                {"pending_id": request.pending_id, "reviewer": request.reviewer},
            )
            return ApproveResponse(status="rejected", pending_id=request.pending_id)

        result = self.execute_action(pending.action, None, pending.draft_response)
        self.store.log_event(
            "pending_approved",
            {"pending_id": request.pending_id, "reviewer": request.reviewer, "result": result},
        )
        return ApproveResponse(status="approved", pending_id=request.pending_id, result=result)

    def classify_request(self, text: str) -> ClassificationResult:
        """Classify request category, urgency, and confidence with simple rules."""
        lowered = text.lower()

        if any(token in lowered for token in ("refund", "charged", "purchase", "transaction", "billing")):
            category = "billing"
            urgency = "high" if "charged" in lowered or "refund" in lowered else "medium"
            confidence = 0.9
        elif any(token in lowered for token in ("hack", "banned", "login", "password", "account")):
            category = "account_access"
            urgency = "critical" if "hack" in lowered else "high"
            confidence = 0.86
        elif any(token in lowered for token in ("crash", "bug", "error", "freeze")):
            category = "bug_report"
            urgency = "high" if "crash" in lowered else "medium"
            confidence = 0.84
        elif any(token in lowered for token in ("aimbot", "cheat", "hacker", "report player")):
            category = "cheater_report"
            urgency = "medium"
            confidence = 0.82
        elif "how" in lowered or "where" in lowered:
            category = "gameplay_question"
            urgency = "low"
            confidence = 0.8
        else:
            category = "other"
            urgency = "low"
            confidence = 0.6

        return ClassificationResult(category=category, urgency=urgency, confidence=confidence)

    def extract_fields(self, payload: WebhookRequest) -> ExtractedFields:
        """Extract basic entities from webhook text."""
        text = payload.text
        txn_match = re.search(r"\bTXN[-_ ]?\d+\b", text, flags=re.IGNORECASE)
        error_match = re.search(r"\bE[-_ ]?\d+\b", text, flags=re.IGNORECASE)

        lowered = text.lower()
        if "iphone" in lowered or "ios" in lowered:
            platform = "iOS"
        elif "android" in lowered:
            platform = "Android"
        elif "ps5" in lowered or "playstation" in lowered:
            platform = "PS5"
        elif "xbox" in lowered:
            platform = "Xbox"
        elif "windows" in lowered or "pc" in lowered:
            platform = "PC"
        else:
            platform = "unknown"

        keywords = [word for word in re.findall(r"[a-zA-Z]{4,}", text.lower())[:8]]

        return ExtractedFields(
            user_id=payload.user_id,
            platform=platform,
            transaction_id=txn_match.group(0) if txn_match else None,
            error_code=error_match.group(0) if error_match else None,
            keywords=keywords,
        )

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

        action = ProposedAction(
            tool="create_ticket_and_reply",
            payload={
                "title": title,
                "text": payload.text,
                "category": classification.category,
                "urgency": classification.urgency,
                "transaction_id": extracted.transaction_id,
            },
            risky=risky,
            risk_reason=reason,
        )
        return action, draft

    def needs_approval(self, text: str, classification: ClassificationResult, action: ProposedAction) -> bool:
        """Determine if action must go through manual approval."""
        lowered = text.lower()
        legal_risk = any(token in lowered for token in ("lawyer", "lawsuit", "press", "gdpr"))
        return action.risky or legal_risk or classification.urgency in {"high", "critical"}

    def execute_action(self, action: ProposedAction, user_id: str | None, draft_response: str) -> dict[str, object]:
        """Execute tool stubs for ticket creation and draft delivery."""
        ticket = create_ticket(action.payload)
        reply = send_reply(user_id, draft_response)
        result: dict[str, object] = {
            "ticket": ticket,
            "reply": reply,
        }
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
