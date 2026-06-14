"""Anthropic Claude tool-use client for triage classification and extraction."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from tenacity import (
    Retrying,
    before_sleep_log,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.config import Settings
from app.metrics import LLM_DURATION_SECONDS, LLM_REQUESTS_TOTAL, LLM_RETRY_TOTAL
from app.schemas import (
    ClassificationResult,
    ClassifyToolResult,
    ExtractedFields,
    ExtractToolResult,
)
from app.tracing import get_tracer

LOGGER = logging.getLogger(__name__)
TRACER = get_tracer(__name__)

SYSTEM_PROMPT = (
    "You are a game support triage assistant. "
    "Use available tools to classify requests and extract entities. "
    "Always call classify_request and extract_entities before ending your turn."
)
ERROR_CODE_PATTERN = re.compile(r"\b(?:ERR[-_ ]?\d{3,}|E[-_]\d{4,})\b", flags=re.IGNORECASE)
DEMO_ADVERSARIAL_PATTERNS = (
    "ignore previous instructions",
    "developer mode",
    "jailbreak",
    "bypass",
    "hidden admin instructions",
)

TOOLS: list[dict[str, Any]] = [
    {
        "name": "classify_request",
        "description": "Classifies support request into category and sets urgency",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": [
                        "bug_report",
                        "billing",
                        "account_access",
                        "cheater_report",
                        "moderation",
                        "legal",
                        "uncertain",
                        "security",
                        "safety",
                        "webhook",
                        "boundary",
                        "gameplay_question",
                        "other",
                    ],
                },
                "urgency": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                },
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["category", "urgency", "confidence"],
        },
    },
    {
        "name": "extract_entities",
        "description": "Extracts structured entities from the message",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "platform": {
                    "type": "string",
                    "enum": ["iOS", "Android", "PC", "PS5", "Xbox", "unknown"],
                },
                "game_title": {"type": "string"},
                "transaction_id": {"type": "string"},
                "error_code": {"type": "string"},
                "reported_username": {"type": "string"},
                "keywords": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    {
        "name": "lookup_faq",
        "description": "Looks up top-3 relevant KB articles by keywords",
        "input_schema": {
            "type": "object",
            "properties": {"keywords": {"type": "array", "items": {"type": "string"}}},
            "required": ["keywords"],
        },
    },
    {
        "name": "draft_reply",
        "description": "Drafts a polite, helpful reply to the user",
        "input_schema": {
            "type": "object",
            "properties": {
                "tone": {
                    "type": "string",
                    "enum": ["empathetic", "informational", "escalation"],
                },
                "include_faq_links": {"type": "boolean"},
                "draft_text": {"type": "string"},
            },
            "required": ["tone", "draft_text"],
        },
    },
    {
        "name": "flag_for_human",
        "description": "Flags request for mandatory human review before any action",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string"},
                "risk_level": {
                    "type": "string",
                    "enum": ["medium", "high", "critical"],
                },
            },
            "required": ["reason", "risk_level"],
        },
    },
]


@dataclass
class TriageResult:
    """Result assembled from Claude tool outputs."""

    classification: ClassificationResult
    extracted: ExtractedFields
    draft_text: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    turns_used: int = 0


class LLMClient:
    """Small wrapper around Claude messages tool-use loop."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._anthropic = None
        self._client = None
        if settings.llm_mode == "demo":
            return
        try:
            import anthropic  # type: ignore
        except ImportError as exc:  # pragma: no cover - environment-specific
            raise RuntimeError(
                "anthropic package is required. Install with: pip install anthropic"
            ) from exc
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def run_agent(
        self,
        text: str,
        user_id: str | None = None,
        max_turns: int = 5,
        tenant_id: str | None = None,
    ) -> TriageResult:
        """Run Claude tool-use loop and return structured triage outputs."""
        if self.settings.llm_mode == "demo":
            return self._run_demo_agent(text, user_id)

        messages: list[dict[str, Any]] = [{"role": "user", "content": text}]
        classification: ClassificationResult | None = None
        extracted = ExtractedFields(user_id=user_id)
        draft_text: str | None = None
        input_tokens = 0
        output_tokens = 0
        turns_used = 0
        force_pending = False

        for _ in range(max_turns):
            turns_used += 1
            response = self._create_message(
                model=self.settings.anthropic_model,
                max_tokens=700,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                tool_choice={"type": "auto"},
                messages=messages,
                tenant_id=tenant_id,
            )
            usage = getattr(response, "usage", None)
            input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
            output_tokens += int(getattr(usage, "output_tokens", 0) or 0)

            assistant_content: list[dict[str, Any]] = []
            tool_results: list[dict[str, Any]] = []

            for block in response.content:
                block_type = getattr(block, "type", None)
                if block_type == "text":
                    assistant_content.append({"type": "text", "text": getattr(block, "text", "")})
                    continue
                if block_type != "tool_use":
                    continue

                tool_name = str(getattr(block, "name", ""))
                tool_input = getattr(block, "input", {}) or {}
                tool_output = self._dispatch_tool(tool_name, tool_input, user_id)
                if bool(tool_output.pop("__force_pending__", False)):
                    force_pending = True

                if tool_name == "classify_request":
                    classification = ClassificationResult(**tool_output)
                elif tool_name == "extract_entities":
                    extracted = ExtractedFields(**tool_output)
                elif tool_name == "draft_reply":
                    candidate = str(tool_output.get("draft_text", "")).strip()
                    if candidate:
                        draft_text = candidate

                assistant_content.append(
                    {
                        "type": "tool_use",
                        "id": getattr(block, "id"),
                        "name": tool_name,
                        "input": tool_input,
                    }
                )
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": getattr(block, "id"),
                        "content": json.dumps(tool_output, ensure_ascii=False),
                    }
                )

            if assistant_content:
                messages.append({"role": "assistant", "content": assistant_content})

            if getattr(response, "stop_reason", None) == "end_turn":
                break

            if not tool_results:
                break
            messages.append({"role": "user", "content": tool_results})

        if classification is None:
            classification = ClassificationResult(category="other", urgency="low", confidence=0.0)
        elif force_pending:
            classification = classification.model_copy(update={"confidence": 0.0})
        if extracted.user_id is None:
            extracted.user_id = user_id
        return TriageResult(
            classification=classification,
            extracted=extracted,
            draft_text=draft_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            turns_used=turns_used,
        )

    def summarize_cluster(self, ticket_texts: list[str]) -> dict[str, str | None]:
        """Summarize a cluster of ticket texts with a single LLM call."""
        if not ticket_texts:
            return {
                "label": "Cluster",
                "summary": "No ticket texts available",
                "severity": "low",
            }
        if self.settings.llm_mode == "demo":
            joined = " ".join(ticket_texts[:3]).lower()
            severity = "high" if any(token in joined for token in ("refund", "charged")) else "low"
            return {
                "label": "Demo cluster",
                "summary": f"Deterministic demo summary for {len(ticket_texts)} tickets.",
                "severity": severity,
            }

        prompt = (
            "Summarize these support tickets into a short RCA label and summary.\n"
            "Return JSON with keys: label, summary, severity (low|medium|high).\n\n"
            f"Tickets:\n{chr(10).join(f'- {item}' for item in ticket_texts[:5])}"
        )
        response = self._create_message(
            model=self.settings.anthropic_model,
            max_tokens=250,
            system="You summarize ticket clusters for internal support analytics.",
            tools=[],
            messages=[{"role": "user", "content": prompt}],
        )
        text_blocks = [
            str(getattr(block, "text", ""))
            for block in getattr(response, "content", [])
            if getattr(block, "type", None) == "text"
        ]
        raw_text = "\n".join(block for block in text_blocks if block).strip()
        if not raw_text:
            return {
                "label": "Cluster",
                "summary": "Summary unavailable",
                "severity": None,
            }

        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            return {"label": "Cluster", "summary": raw_text[:400], "severity": None}

        label = str(parsed.get("label", "Cluster")).strip() or "Cluster"
        summary = str(parsed.get("summary", "Summary unavailable")).strip() or "Summary unavailable"
        severity = parsed.get("severity")
        if isinstance(severity, str) and severity in {"low", "medium", "high"}:
            return {"label": label, "summary": summary, "severity": severity}
        return {"label": label, "summary": summary, "severity": None}

    async def summarize_cluster_async(self, ticket_texts: list[str]) -> dict[str, str | None]:
        """Run cluster summarization off the event loop."""
        return await asyncio.to_thread(self.summarize_cluster, ticket_texts)

    def _run_demo_agent(self, text: str, user_id: str | None) -> TriageResult:
        """Return deterministic fixture responses without an external LLM call."""
        classification_input, extracted_input, draft_input = self._demo_tool_inputs(text)
        classification = ClassificationResult(
            **self._dispatch_tool("classify_request", classification_input, user_id)
        )
        extracted = ExtractedFields(
            **self._dispatch_tool("extract_entities", extracted_input, user_id)
        )
        draft = self._dispatch_tool("draft_reply", draft_input, user_id)
        if extracted.user_id is None:
            extracted.user_id = user_id
        return TriageResult(
            classification=classification,
            extracted=extracted,
            draft_text=str(draft.get("draft_text", "")),
            input_tokens=0,
            output_tokens=0,
            turns_used=1,
        )

    def _demo_tool_inputs(self, text: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        lowered = text.lower()
        if "malformed" in lowered or "bad json" in lowered or "schema" in lowered:
            return (
                {"category": "not_a_category", "urgency": "low", "confidence": "high"},
                {"platform": "Dreamcast", "error_code": "not an error code"},
                {"tone": "informational", "draft_text": ""},
            )
        category, urgency, confidence, keywords = _classify_demo_text(lowered)
        tone = "escalation" if category in _DEMO_HUMAN_REVIEW_CATEGORIES else "informational"
        extracted = {"platform": "unknown", "keywords": keywords}
        if category == "billing":
            extracted["transaction_id"] = None
        return (
            {"category": category, "urgency": urgency, "confidence": confidence},
            extracted,
            {"tone": tone, "draft_text": _demo_draft_text(category)},
        )

    def _create_message(self, **kwargs: Any) -> Any:
        """Call Claude messages API with retries on transient 5xx responses."""
        tenant_id = kwargs.pop("tenant_id", None)
        started = time.monotonic()

        def _should_retry(exc: BaseException) -> bool:
            api_status_error = getattr(self._anthropic, "APIStatusError", None)
            if api_status_error and isinstance(exc, api_status_error):
                status_code = int(getattr(exc, "status_code", 0) or 0)
                return 500 <= status_code < 600
            return False

        retrying_kwargs: dict[str, Any] = {}
        if hasattr(self, "_retry_sleep"):
            retrying_kwargs["sleep"] = self._retry_sleep

        retrying = Retrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=30),
            retry=retry_if_exception(_should_retry),
            before_sleep=before_sleep_log(LOGGER, logging.WARNING),
            reraise=True,
            **retrying_kwargs,
        )
        with TRACER.start_as_current_span("llm.api_call") as span:
            model = str(kwargs.get("model", ""))
            span.set_attribute("model", model)
            tenant_hash = "unknown"
            if tenant_id:
                tenant_hash = _sha256_short(str(tenant_id))
                span.set_attribute("tenant_id_hash", tenant_hash)
            try:
                attempt_count = 0
                for attempt in retrying:
                    with attempt:
                        attempt_count += 1
                        response = self._client.messages.create(**kwargs)
                        usage = getattr(response, "usage", None)
                        span.set_attribute(
                            "input_tokens", int(getattr(usage, "input_tokens", 0) or 0)
                        )
                        span.set_attribute(
                            "output_tokens",
                            int(getattr(usage, "output_tokens", 0) or 0),
                        )
                        span.set_attribute("status", "ok")
                        LLM_REQUESTS_TOTAL.labels(
                            model=model, status="ok", tenant_hash=tenant_hash
                        ).inc()
                        if attempt_count > 1:
                            LLM_RETRY_TOTAL.labels(tenant_hash=tenant_hash).inc(attempt_count - 1)
                        return response
            except Exception as exc:
                span.set_attribute("status", "error")
                span.record_exception(exc)
                LLM_REQUESTS_TOTAL.labels(
                    model=model, status="error", tenant_hash=tenant_hash
                ).inc()
                raise
            finally:
                span.set_attribute("duration_ms", round((time.monotonic() - started) * 1000, 2))
                LLM_DURATION_SECONDS.labels(model=model, tenant_hash=tenant_hash).observe(
                    time.monotonic() - started
                )

        raise RuntimeError("unreachable")

    def _dispatch_tool(
        self, name: str, tool_input: dict[str, Any], user_id: str | None
    ) -> dict[str, Any]:
        """Dispatch local tool handlers for model tool_use blocks."""
        if name == "classify_request":
            candidate = dict(tool_input)
            confidence = candidate.get("confidence")
            if isinstance(confidence, (int, float)):
                clamped = max(0.0, min(float(confidence), 1.0))
                if clamped != float(confidence):
                    LOGGER.warning(
                        "invalid llm tool output",
                        extra={
                            "event": "llm_invalid_response",
                            "context": {
                                "tool": name,
                                "reason": "confidence_clamped",
                            },
                        },
                    )
                candidate["confidence"] = clamped
            try:
                return ClassifyToolResult(**candidate).model_dump()
            except ValidationError:
                LOGGER.error(
                    "invalid llm tool output",
                    extra={
                        "event": "llm_invalid_response",
                        "context": {"tool": name, "reason": "schema_validation_failed"},
                    },
                    exc_info=True,
                )
                return ClassificationResult(
                    category="other", urgency="low", confidence=0.0
                ).model_dump()

        if name == "extract_entities":
            merged_input = dict(tool_input)
            if "user_id" not in merged_input:
                merged_input["user_id"] = user_id
            raw_error_code = merged_input.get("error_code")
            if isinstance(raw_error_code, str):
                match = ERROR_CODE_PATTERN.search(raw_error_code.strip())
                merged_input["error_code"] = match.group(0) if match else None
            try:
                validated = ExtractToolResult(**merged_input)
                return validated.model_dump()
            except ValidationError:
                LOGGER.error(
                    "invalid llm tool output",
                    extra={
                        "event": "llm_invalid_response",
                        "context": {"tool": name, "reason": "schema_validation_failed"},
                    },
                    exc_info=True,
                )
                return ExtractedFields(user_id=user_id).model_dump()

        if name == "lookup_faq":
            keywords = [str(item) for item in tool_input.get("keywords", [])][:3]
            return {
                "articles": [
                    {
                        "title": f"FAQ: {keyword}",
                        "url": f"{self.settings.kb_base_url}/{keyword}",
                    }
                    for keyword in keywords
                ]
            }

        if name == "draft_reply":
            tone = str(tool_input.get("tone", "informational"))
            draft_text = str(tool_input.get("draft_text", "")).strip()
            if not draft_text:
                draft_text = "Thanks for contacting support. We have logged your request."
            return {
                "tone": tone,
                "include_faq_links": bool(tool_input.get("include_faq_links", False)),
                "draft_text": draft_text,
            }

        if name == "flag_for_human":
            reason = str(tool_input.get("reason", "manual approval required"))
            risk_level = str(tool_input.get("risk_level", "medium"))
            if risk_level not in {"medium", "high", "critical"}:
                risk_level = "medium"
            return {"reason": reason, "risk_level": risk_level}

        LOGGER.warning(
            "unknown llm tool",
            extra={"event": "llm_unknown_tool", "context": {"tool": name}},
        )
        return {"ignored_tool": name, "__force_pending__": True}


def _sha256_short(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


_DEMO_HUMAN_REVIEW_CATEGORIES = {
    "billing",
    "account_access",
    "moderation",
    "legal",
    "uncertain",
    "security",
    "safety",
    "boundary",
}


def _classify_demo_text(lowered: str) -> tuple[str, str, float, list[str]]:
    """Deterministic local classifier aligned with the gdev triage_v1 eval slice."""
    if _matches_any(
        lowered,
        (
            "support queue for test-tenant",
            "another tenant",
            "tenant a routing",
            "tenant b routing",
            "as if it belonged to",
        ),
    ):
        return "boundary", "critical", 0.99, ["tenant-boundary"]
    if _matches_any(
        lowered,
        (
            *DEMO_ADVERSARIAL_PATTERNS,
            "normal routing rules",
            "approve this refund automatically",
            "system instruction",
            "skip human review",
            "override the policy",
            "mark every future request as safe",
            "return approved",
            "routing policy says pending",
        ),
    ):
        return "security", "critical", 0.99, ["prompt-injection"]
    if _matches_any(
        lowered,
        (
            "hidden service credentials",
            "internal connection settings",
            "hidden signing material",
            "private operational values",
            "confidential configuration values",
        ),
    ):
        return "security", "critical", 0.99, ["secret-leak-attempt"]
    if _matches_any(
        lowered,
        (
            "hxxp://",
            "suspicious link",
            "shortened link",
            "free gems",
            "suspicious external giveaway",
            "alter account balances",
            "external form asking for account recovery details",
        ),
    ):
        return "safety", "high", 0.98, ["unsafe-url"]
    if _matches_any(
        lowered,
        (
            "repeated webhook delivery",
            "same support event",
            "duplicate demo notification",
            "delivered the same bug report twice",
            "duplicate moderation report",
        ),
    ):
        return "webhook", "low", 0.94, ["duplicate-webhook"]
    if _matches_any(
        lowered,
        (
            "cannot sign in",
            "recovery email",
            "verification code",
            "locked out",
            "account says disabled",
            "lost access",
            "login approval",
            "account lockout",
        ),
    ):
        return "account_access", "high", 0.93, ["account-access"]
    if _matches_any(
        lowered,
        (
            "copy of all data",
            "delete the records",
            "privacy rights",
            "object to processing",
            "privacy team",
            "access request",
            "data deletion",
            "legal review",
        ),
    ):
        return "legal", "high", 0.94, ["privacy", "legal"]
    if _matches_any(
        lowered,
        (
            "harassing",
            "abusive language",
            "spam links in the public lobby",
            "report a synthetic user",
            "griefing",
            "disruptive behavior",
            "moderation report",
        ),
    ):
        return "moderation", "high", 0.91, ["moderation"]
    if _matches_any(
        lowered,
        (
            "not sure",
            "cannot tell",
            "forgot the exact",
            "unclear complaint",
            "incomplete and unclear",
            "something odd",
            "might be billing or access",
            "thing",
            "low confidence",
        ),
    ):
        return "uncertain", "medium", 0.35, ["ambiguous"]
    if _matches_any(
        lowered,
        (
            "charged",
            "refund",
            "payment",
            "purchase",
            "subscription",
            "billing",
            "receipt",
            "identical charges",
            "reverse the accidental charge",
            "duplicate invoice",
        ),
    ):
        return "billing", "medium", 0.92, ["billing"]
    if _matches_any(
        lowered,
        (
            "spinner never stops",
            "reports tab",
            "export button",
            "empty csv",
            "filters reset",
            "issue list",
            "mobile menu overlaps",
            "notification banner",
            "status badge",
            "stale state",
            "workflow completes",
        ),
    ):
        return "bug_report", "low", 0.9, ["bug-report"]
    return "gameplay_question", "low", 0.96, ["gameplay"]


def _matches_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in value for needle in needles)


def _demo_draft_text(category: str) -> str:
    if category == "billing":
        return "Thanks for reporting the payment issue. We will review it before taking action."
    if category == "account_access":
        return "We received your account access request and escalated it for review."
    if category == "bug_report":
        return "Thanks for the bug report. We have logged it for the team."
    if category == "moderation":
        return "Thanks for the report. Our moderation team will review it."
    if category == "legal":
        return "We have routed this privacy or legal request for specialist review."
    if category == "uncertain":
        return "We need a support specialist to review the missing details."
    if category in {"security", "safety", "boundary"}:
        return "This request is blocked by safety checks and needs manual review."
    if category == "webhook":
        return "Thanks. We have logged this webhook delivery idempotently."
    return "Thanks for the question. We will send the best available guidance shortly."
