"""Core agent decision logic for request triage."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from decimal import Decimal
from queue import Queue
import threading
import time
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text

from app.approval_store import RedisApprovalStore
from app.config import Settings
from app.cost_ledger import BudgetExhaustedError, CostLedger
from app.embedding_service import EmbeddingService
from app.guardrails.output_guard import OutputGuard
from app.integrations.sheets import SheetsClient
from app.integrations.telegram import TelegramClient
from app.llm_client import LLMClient
from app.logging import REQUEST_ID
from app.metrics import (
    APPROVED_TOTAL,
    BUDGET_EXCEEDED_TOTAL,
    BUDGET_UTILIZATION_RATIO,
    GUARD_BLOCKS_TOTAL,
    GUARD_REDACTIONS_TOTAL,
    INJECTION_ATTEMPTS_TOTAL,
    LLM_COST_USD_TOTAL,
    LLM_REQUESTS_TOTAL,
    LLM_TOKENS_TOTAL,
    LLM_TURNS_USED,
    PENDING_TOTAL,
    REJECTED_TOTAL,
    REQUEST_DURATION_SECONDS,
    REQUESTS_TOTAL,
)
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
try:  # pragma: no cover - optional dependency in minimal local envs
    from opentelemetry import trace  # type: ignore[import-not-found]

    TRACER = trace.get_tracer(__name__)
except Exception:  # pragma: no cover - fallback when opentelemetry is unavailable

    class _NoopSpan:
        def __enter__(self) -> "_NoopSpan":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def set_attribute(self, _name: str, _value: object) -> None:
            return None

        def record_exception(self, _exc: BaseException) -> None:
            return None

    class _NoopTracer:
        def start_as_current_span(self, _name: str) -> _NoopSpan:
            return _NoopSpan()

    TRACER = _NoopTracer()

INJECTION_PATTERNS = (
    "ignore previous instructions",
    "system:",
    "[inst]",
    "[/inst]",
    "act as if you",
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
        cost_ledger: CostLedger | None = None,
        embedding_service: EmbeddingService | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.approval_store = approval_store
        self.llm_client = llm_client or LLMClient(settings)
        self.output_guard = output_guard or OutputGuard(settings)
        self.telegram_client = telegram_client
        self.sheets_client = sheets_client
        self.cost_ledger = cost_ledger or CostLedger()
        self.embedding_service = embedding_service

    def process_webhook(
        self, payload: WebhookRequest, message_id: str | None = None
    ) -> WebhookResponse:
        """Run the full agent flow and return either executed or pending result."""
        start = time.monotonic()
        tenant_hash = (
            hashlib.sha256(payload.tenant_id.encode("utf-8")).hexdigest()[:16]
            if payload.tenant_id
            else None
        )
        metric_tenant_hash = tenant_hash or "unknown"
        with TRACER.start_as_current_span("agent.input_guard") as span:
            if tenant_hash is not None:
                span.set_attribute("tenant_id_hash", tenant_hash)
            span.set_attribute("text_length", len(payload.text))
            try:
                self._guard_input(payload.text)
            except Exception as exc:
                span.set_attribute("blocked", True)
                INJECTION_ATTEMPTS_TOTAL.labels(tenant_hash=metric_tenant_hash).inc()
                span.record_exception(exc)
                raise
            span.set_attribute("blocked", False)

        with TRACER.start_as_current_span("agent.budget_check") as span:
            if tenant_hash is not None:
                span.set_attribute("tenant_id_hash", tenant_hash)
            try:
                self._enforce_budget(payload.tenant_id)
            except Exception as exc:
                span.set_attribute("allowed", False)
                span.record_exception(exc)
                raise
            span.set_attribute("allowed", True)

        with TRACER.start_as_current_span("agent.llm_classify") as span:
            if tenant_hash is not None:
                span.set_attribute("tenant_id_hash", tenant_hash)
            span.set_attribute("model", self.settings.anthropic_model)
            try:
                triage = self.llm_client.run_agent(
                    payload.text, payload.user_id, tenant_id=payload.tenant_id
                )
            except TypeError:
                triage = self.llm_client.run_agent(payload.text, payload.user_id)
            classification = triage.classification
            cost_usd = self._estimate_llm_cost_usd(
                triage.input_tokens, triage.output_tokens
            )
            span.set_attribute("input_tokens", triage.input_tokens)
            span.set_attribute("output_tokens", triage.output_tokens)
            span.set_attribute("cost_usd", cost_usd)
            span.set_attribute("turns_used", triage.turns_used)
            span.set_attribute("category", classification.category)
            span.set_attribute("urgency", classification.urgency)
            span.set_attribute("confidence", classification.confidence)
            LLM_REQUESTS_TOTAL.labels(
                model=self.settings.anthropic_model,
                status="ok",
                tenant_hash=metric_tenant_hash,
            ).inc()
            LLM_TOKENS_TOTAL.labels(
                direction="input",
                model=self.settings.anthropic_model,
                tenant_hash=metric_tenant_hash,
            ).inc(triage.input_tokens)
            LLM_TOKENS_TOTAL.labels(
                direction="output",
                model=self.settings.anthropic_model,
                tenant_hash=metric_tenant_hash,
            ).inc(triage.output_tokens)
            LLM_COST_USD_TOTAL.labels(
                model=self.settings.anthropic_model, tenant_hash=metric_tenant_hash
            ).inc(cost_usd)
            LLM_TURNS_USED.labels(tenant_hash=metric_tenant_hash).observe(
                triage.turns_used
            )

        extracted = triage.extracted
        with TRACER.start_as_current_span("agent.propose_action") as span:
            if tenant_hash is not None:
                span.set_attribute("tenant_id_hash", tenant_hash)
            action, fallback_draft = self.propose_action(
                payload, classification, extracted
            )
            span.set_attribute("tool", action.tool)
            span.set_attribute("risky", action.risky)
            span.set_attribute("risk_reason", action.risk_reason or "")
        draft_response = triage.draft_text or fallback_draft
        self._record_cost_best_effort(
            payload.tenant_id, triage.input_tokens, triage.output_tokens, cost_usd
        )

        with TRACER.start_as_current_span("agent.output_guard") as span:
            if tenant_hash is not None:
                span.set_attribute("tenant_id_hash", tenant_hash)
            guard_result = self.output_guard.scan(
                draft_response, classification.confidence, action
            )
            span.set_attribute("blocked", guard_result.blocked)
            span.set_attribute(
                "redacted", guard_result.redacted_draft != draft_response
            )
            span.set_attribute(
                "url_stripped", guard_result.redacted_draft != draft_response
            )
            if guard_result.blocked:
                GUARD_BLOCKS_TOTAL.labels(
                    guard_type="output",
                    reason="blocked_response",
                    tenant_hash=metric_tenant_hash,
                ).inc()
            if guard_result.redacted_draft != draft_response:
                GUARD_REDACTIONS_TOTAL.labels(
                    guard_type="output", tenant_hash=metric_tenant_hash
                ).inc()
        if guard_result.blocked:
            raise HTTPException(
                status_code=500, detail="Internal: output guard blocked response"
            )
        if guard_result.action_override is not None:
            action = guard_result.action_override
        if guard_result.redacted_draft != draft_response:
            LOGGER.info(
                "output redacted",
                extra={
                    "event": "output_guard_redacted",
                    "context": {"request_id": REQUEST_ID.get()},
                },
            )
        draft_response = guard_result.redacted_draft

        with TRACER.start_as_current_span("agent.route") as span:
            if tenant_hash is not None:
                span.set_attribute("tenant_id_hash", tenant_hash)
            route_pending = self.needs_approval(payload.text, classification, action)
            span.set_attribute("outcome", "pending" if route_pending else "executed")

        if route_pending:
            PENDING_TOTAL.labels(tenant_hash=metric_tenant_hash).inc()
            pending = PendingDecision(
                pending_id=uuid4().hex,
                tenant_id=str(payload.tenant_id or ""),
                reason=action.risk_reason or "manual approval required",
                user_id=payload.user_id,
                expires_at=datetime.now(UTC)
                + timedelta(seconds=self.settings.approval_ttl_seconds),
                action=action,
                draft_response=draft_response,
            )
            self.approval_store.put_pending(pending)
            latency_ms = round((time.monotonic() - start) * 1000)
            audit_entry = AuditLogEntry(
                timestamp=datetime.now(UTC).isoformat(),
                request_id=REQUEST_ID.get(),
                tenant_id=payload.tenant_id,
                message_id=message_id,
                user_id=hashlib.sha256(payload.user_id.encode()).hexdigest()
                if payload.user_id
                else None,
                category=classification.category,
                urgency=classification.urgency,
                confidence=classification.confidence,
                action=action.tool,
                status="pending",
                approved_by=None,
                ticket_id=None,
                latency_ms=latency_ms,
                cost_usd=cost_usd,
            )
            ticket_id = self.store.persist_pipeline_run(
                payload,
                classification,
                extracted,
                action,
                audit_entry,
                input_tokens=triage.input_tokens,
                output_tokens=triage.output_tokens,
            )
            self._schedule_embedding(
                ticket_id=ticket_id,
                tenant_id=payload.tenant_id,
                text_value=payload.text,
            )
            self.store.log_event(
                "pending_created",
                {
                    **pending.model_dump(mode="json"),
                    "tenant_id": payload.tenant_id,
                },
            )
            self._notify_approval_channel(pending, classification)
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
            REQUESTS_TOTAL.labels(
                status="pending",
                category=classification.category,
                urgency=classification.urgency,
                tenant_hash=metric_tenant_hash,
            ).inc()
            REQUEST_DURATION_SECONDS.labels(
                endpoint="/webhook", tenant_hash=metric_tenant_hash
            ).observe(time.monotonic() - start)
            return WebhookResponse(
                status="pending",
                classification=classification,
                extracted=extracted,
                action=action,
                draft_response=draft_response,
                pending=pending,
            )

        action_result = self.execute_action(
            action,
            payload.user_id,
            draft_response,
            tenant_id=payload.tenant_id,
            event_context={
                "input_tokens": triage.input_tokens,
                "output_tokens": triage.output_tokens,
                "cost_usd": cost_usd,
            },
        )
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

        audit_entry = AuditLogEntry(
            timestamp=datetime.now(UTC).isoformat(),
            request_id=REQUEST_ID.get(),
            tenant_id=payload.tenant_id,
            message_id=message_id,
            user_id=hashlib.sha256(payload.user_id.encode()).hexdigest()
            if payload.user_id
            else None,
            category=classification.category,
            urgency=classification.urgency,
            confidence=classification.confidence,
            action=action.tool,
            status="executed",
            approved_by="auto",
            ticket_id=str(action_result.get("ticket", {}).get("ticket_id", "")),
            latency_ms=latency_ms,
            cost_usd=cost_usd,
        )
        ticket_id = self.store.persist_pipeline_run(
            payload,
            classification,
            extracted,
            action,
            audit_entry,
            input_tokens=triage.input_tokens,
            output_tokens=triage.output_tokens,
        )
        self._schedule_embedding(
            ticket_id=ticket_id, tenant_id=payload.tenant_id, text_value=payload.text
        )
        self._append_audit_async(audit_entry)
        REQUESTS_TOTAL.labels(
            status="executed",
            category=classification.category,
            urgency=classification.urgency,
            tenant_hash=metric_tenant_hash,
        ).inc()
        REQUEST_DURATION_SECONDS.labels(
            endpoint="/webhook", tenant_hash=metric_tenant_hash
        ).observe(time.monotonic() - start)

        return WebhookResponse(
            status="executed",
            classification=classification,
            extracted=extracted,
            action=action,
            draft_response=draft_response,
            action_result=action_result,
        )

    def approve(
        self,
        request: ApproveRequest,
        jwt_tenant_id: str | None = None,
    ) -> ApproveResponse:
        """Approve or reject a pending action."""
        reviewer_hash = (
            hashlib.sha256((request.reviewer or "").encode()).hexdigest()[:16]
            if request.reviewer
            else None
        )
        pending = self.approval_store.get_pending(request.pending_id)
        if not pending:
            raise HTTPException(status_code=404, detail="pending_id not found")
        if jwt_tenant_id is None or str(pending.tenant_id) != str(jwt_tenant_id):
            raise HTTPException(status_code=403, detail="Forbidden")

        pending = self.approval_store.pop_pending(request.pending_id)
        if not pending:
            raise HTTPException(status_code=404, detail="pending_id not found")

        tenant_id = pending.tenant_id
        if not request.approved:
            self._record_approval_event(
                pending_id=str(pending.pending_id),
                tenant_id=str(tenant_id),
                decision="rejected",
                reviewer_hash=reviewer_hash,
            )
            REJECTED_TOTAL.labels(tenant_hash=_sha256_short(str(tenant_id))).inc()
            self.store.log_event(
                "pending_rejected",
                {
                    "pending_id": request.pending_id,
                    "reviewer": reviewer_hash,
                    "tenant_id": tenant_id,
                },
            )
            return ApproveResponse(status="rejected", pending_id=request.pending_id)

        started = time.monotonic()
        result = self.execute_action(
            pending.action,
            pending.user_id,
            pending.draft_response,
            tenant_id=str(tenant_id) if tenant_id is not None else None,
        )
        latency_ms = round((time.monotonic() - started) * 1000)
        self.store.log_event(
            "pending_approved",
            {
                "pending_id": request.pending_id,
                "reviewer": reviewer_hash,
                "result": result,
                "tenant_id": tenant_id,
            },
        )
        self._append_audit_async(
            AuditLogEntry(
                timestamp=datetime.now(UTC).isoformat(),
                request_id=REQUEST_ID.get(),
                tenant_id=str(tenant_id) if tenant_id is not None else None,
                message_id=None,
                user_id=hashlib.sha256(pending.user_id.encode()).hexdigest()
                if pending.user_id
                else None,
                category=str(pending.action.payload.get("category", "other")),
                urgency=str(pending.action.payload.get("urgency", "low")),
                confidence=0.0,
                action=pending.action.tool,
                status="approved",
                approved_by=reviewer_hash,
                ticket_id=str(result.get("ticket", {}).get("ticket_id", "")),
                latency_ms=latency_ms,
                cost_usd=0.0,
            )
        )
        self._record_approval_event(
            pending_id=str(pending.pending_id),
            tenant_id=str(tenant_id),
            decision="approved",
            reviewer_hash=reviewer_hash,
        )
        APPROVED_TOTAL.labels(tenant_hash=_sha256_short(str(tenant_id))).inc()
        return ApproveResponse(
            status="approved", pending_id=request.pending_id, result=result
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
                "tenant_id": payload.tenant_id,
            },
            risky=risky,
            risk_reason=reason,
        )
        return action, draft

    def needs_approval(
        self, text: str, classification: ClassificationResult, action: ProposedAction
    ) -> bool:
        """Determine if action must go through manual approval."""
        _ = (text, classification)
        return action.risky

    def execute_action(
        self,
        action: ProposedAction,
        user_id: str | None,
        draft_response: str,
        tenant_id: str | None = None,
        event_context: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Execute tool handlers from the tool registry."""
        handler = TOOL_REGISTRY.get(action.tool)
        if handler is None:
            raise ValueError(f"Unknown tool: {action.tool!r}")

        payload = dict(action.payload)
        payload["draft_response"] = draft_response
        result = handler(payload, user_id)
        event_payload = dict(result)
        if event_context:
            event_payload.update(event_context)
        event_payload["tenant_id"] = tenant_id
        self.store.log_event("action_executed", event_payload)
        return result

    def _guard_input(self, text: str) -> None:
        """Validate incoming text and raise ValueError on guardrail hit."""
        if len(text) > self.settings.max_input_length:
            raise ValueError(
                f"Input exceeds max length ({self.settings.max_input_length})"
            )
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

    def _notify_approval_channel(
        self, pending: PendingDecision, classification: ClassificationResult
    ) -> None:
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
                extra={
                    "event": "approval_notify_failed",
                    "context": {"pending_id": pending.pending_id},
                },
                exc_info=True,
            )

    def _append_audit_async(self, entry: AuditLogEntry) -> None:
        """Write audit logs without blocking request completion."""
        if not self.sheets_client:
            return
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.run_in_executor(None, self.sheets_client.append_log, entry)
                return
        except RuntimeError:
            pass
        threading.Thread(
            target=self.sheets_client.append_log, args=(entry,), daemon=True
        ).start()

    def _estimate_llm_cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        """Estimate LLM cost in USD from token usage."""
        return float(
            (Decimal(input_tokens) / Decimal(1000))
            * self.settings.llm_input_rate_per_1k
            + (Decimal(output_tokens) / Decimal(1000))
            * self.settings.llm_output_rate_per_1k
        )

    def _tenant_uuid(self, tenant_id: str | None) -> UUID | None:
        if tenant_id is None:
            return None
        try:
            return UUID(str(tenant_id))
        except (ValueError, TypeError):
            return None

    def _run_blocking(self, coroutine):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coroutine)

        queue: Queue[tuple[bool, object]] = Queue(maxsize=1)

        def _target() -> None:
            try:
                result = asyncio.run(coroutine)
                queue.put((True, result))
            except Exception as exc:  # pragma: no cover - defensive branch
                queue.put((False, exc))

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()
        ok, data = queue.get()
        thread.join()
        if ok:
            return data
        raise data  # type: ignore[misc]

    def _enforce_budget(self, tenant_id: str | None) -> None:
        tenant_uuid = self._tenant_uuid(tenant_id)
        session_factory = getattr(self.store, "_db_session_factory", None)
        # Unit-test fallback only. Production callers always have a valid tenant_uuid
        # because main.py validates it before calling process_webhook().
        if tenant_uuid is None or session_factory is None:
            return

        async def _check_budget() -> None:
            async with session_factory() as session:
                async with session.begin():
                    await session.execute(
                        text("SET LOCAL app.current_tenant_id = :tenant_id"),
                        {"tenant_id": str(tenant_uuid)},
                    )
                    await self.cost_ledger.check_budget(tenant_uuid, session)

        try:
            self._run_blocking(_check_budget())
        except BudgetExhaustedError as exc:
            if tenant_uuid is not None:
                BUDGET_EXCEEDED_TOTAL.labels(
                    tenant_hash=_sha256_short(str(tenant_uuid))
                ).inc()
            raise HTTPException(
                status_code=429, detail={"error": {"code": "budget_exhausted"}}
            ) from exc

    def _record_cost_best_effort(
        self,
        tenant_id: str | None,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None:
        tenant_uuid = self._tenant_uuid(tenant_id)
        session_factory = getattr(self.store, "_db_session_factory", None)
        if tenant_uuid is None or session_factory is None:
            return

        async def _record() -> None:
            async with session_factory() as session:
                async with session.begin():
                    await session.execute(
                        text("SET LOCAL app.current_tenant_id = :tenant_id"),
                        {"tenant_id": str(tenant_uuid)},
                    )
                    await self.cost_ledger.record(
                        tenant_id=tenant_uuid,
                        day=date.today(),
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cost_usd=Decimal(str(cost_usd)),
                        db=session,
                    )
                    budget_row = (
                        (
                            await session.execute(
                                text(
                                    """
                                    SELECT cost_usd, daily_budget_usd
                                    FROM cost_ledger
                                    JOIN tenants USING (tenant_id)
                                    WHERE tenant_id = :tenant_id AND date = :day
                                    """
                                ),
                                {"tenant_id": str(tenant_uuid), "day": date.today()},
                            )
                        )
                        .mappings()
                        .first()
                    )
                    if budget_row:
                        cost_value = Decimal(str(budget_row["cost_usd"] or "0"))
                        budget_value = Decimal(
                            str(budget_row["daily_budget_usd"] or "0")
                        )
                        utilization = (
                            float(cost_value / budget_value)
                            if budget_value > 0
                            else 0.0
                        )
                        BUDGET_UTILIZATION_RATIO.labels(
                            tenant_hash=_sha256_short(str(tenant_uuid))
                        ).set(utilization)

        try:
            self._run_blocking(_record())
        except Exception:
            LOGGER.warning(
                "failed recording llm cost",
                extra={
                    "event": "cost_ledger_record_failed",
                "context": {"tenant_id_hash": _sha256_short(str(tenant_uuid))},
            },
            exc_info=True,
        )

    def _record_approval_event(
        self,
        *,
        pending_id: str,
        tenant_id: str,
        decision: str,
        reviewer_hash: str | None,
    ) -> None:
        session_factory = getattr(self.store, "_db_session_factory", None)
        if session_factory is None:
            return
        try:
            pending_uuid = UUID(str(pending_id))
            tenant_uuid = UUID(str(tenant_id))
        except (ValueError, TypeError):
            LOGGER.error(
                "invalid approval event identifiers",
                extra={
                    "event": "approval_event_invalid_identifiers",
                    "context": {"tenant_id_hash": _sha256_short(str(tenant_id))},
                },
                exc_info=True,
            )
            raise

        async def _record() -> None:
            async with session_factory() as session:
                async with session.begin():
                    await session.execute(
                        text("SET LOCAL app.current_tenant_id = :tenant_id"),
                        {"tenant_id": str(tenant_uuid)},
                    )
                    await session.execute(
                        text(
                            """
                            INSERT INTO approval_events (
                                pending_id, tenant_id, decision, reviewer_id_hash
                            )
                            VALUES (
                                :pending_id, :tenant_id, :decision, :reviewer_id_hash
                            )
                            """
                        ),
                        {
                            "pending_id": str(pending_uuid),
                            "tenant_id": str(tenant_uuid),
                            "decision": decision,
                            "reviewer_id_hash": reviewer_hash,
                        },
                    )
                    await session.execute(
                        text(
                            """
                            UPDATE pending_decisions
                            SET status = :status
                            WHERE pending_id = :pending_id AND tenant_id = :tenant_id
                            """
                        ),
                        {
                            "status": decision,
                            "pending_id": str(pending_uuid),
                            "tenant_id": str(tenant_uuid),
                        },
                    )

        self._run_blocking(_record())

    def _schedule_embedding(
        self, *, ticket_id: str | None, tenant_id: str | None, text_value: str
    ) -> None:
        embedding_service = self.embedding_service
        if embedding_service is None or ticket_id is None or tenant_id is None:
            return

        async def _upsert() -> None:
            try:
                await embedding_service.upsert(
                    tenant_id=tenant_id,
                    ticket_id=ticket_id,
                    text_value=text_value,
                )
            except Exception:
                LOGGER.warning(
                    "embedding upsert failed",
                    extra={
                        "event": "embedding_upsert_failed",
                        "context": {
                            "tenant_id_hash": _sha256_short(tenant_id),
                            "ticket_id": ticket_id,
                        },
                    },
                    exc_info=True,
                )

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_upsert())
        except RuntimeError:
            threading.Thread(target=lambda: asyncio.run(_upsert()), daemon=True).start()


def _sha256_short(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
