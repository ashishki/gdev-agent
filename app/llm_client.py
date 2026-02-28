"""Anthropic Claude tool-use client for triage classification and extraction."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from tenacity import Retrying, before_sleep_log, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import Settings
from app.schemas import ClassificationResult, ExtractedFields

LOGGER = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a game support triage assistant. "
    "Use available tools to classify requests and extract entities. "
    "Always call classify_request and extract_entities before ending your turn."
)
ERROR_CODE_PATTERN = re.compile(r"\b(?:ERR[-_ ]?\d{3,}|E[-_]\d{4,})\b", flags=re.IGNORECASE)

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
                "risk_level": {"type": "string", "enum": ["medium", "high", "critical"]},
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


class LLMClient:
    """Small wrapper around Claude messages tool-use loop."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        try:
            import anthropic  # type: ignore
        except ImportError as exc:  # pragma: no cover - environment-specific
            raise RuntimeError("anthropic package is required. Install with: pip install anthropic") from exc
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def run_agent(self, text: str, user_id: str | None = None, max_turns: int = 5) -> TriageResult:
        """Run Claude tool-use loop and return structured triage outputs."""
        messages: list[dict[str, Any]] = [{"role": "user", "content": text}]
        classification: ClassificationResult | None = None
        extracted = ExtractedFields(user_id=user_id)
        draft_text: str | None = None
        input_tokens = 0
        output_tokens = 0

        for _ in range(max_turns):
            response = self._create_message(
                model=self.settings.anthropic_model,
                max_tokens=700,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                tool_choice={"type": "auto"},
                messages=messages,
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
        if extracted.user_id is None:
            extracted.user_id = user_id
        return TriageResult(
            classification=classification,
            extracted=extracted,
            draft_text=draft_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def _create_message(self, **kwargs: Any) -> Any:
        """Call Claude messages API with retries on transient 5xx responses."""

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
        for attempt in retrying:
            with attempt:
                return self._client.messages.create(**kwargs)

        raise RuntimeError("unreachable")

    def _dispatch_tool(self, name: str, tool_input: dict[str, Any], user_id: str | None) -> dict[str, Any]:
        """Dispatch local tool handlers for model tool_use blocks."""
        if name == "classify_request":
            try:
                return ClassificationResult(**tool_input).model_dump()
            except ValidationError:
                return ClassificationResult(category="other", urgency="low", confidence=0.0).model_dump()

        if name == "extract_entities":
            merged_input = dict(tool_input)
            if "user_id" not in merged_input:
                merged_input["user_id"] = user_id
            raw_error_code = merged_input.get("error_code")
            if isinstance(raw_error_code, str):
                match = ERROR_CODE_PATTERN.search(raw_error_code.strip())
                merged_input["error_code"] = match.group(0) if match else None
            try:
                return ExtractedFields(**merged_input).model_dump()
            except ValidationError:
                return ExtractedFields(user_id=user_id).model_dump()

        if name == "lookup_faq":
            keywords = [str(item) for item in tool_input.get("keywords", [])][:3]
            return {
                "articles": [
                    {"title": f"FAQ: {keyword}", "url": f"{self.settings.kb_base_url}/{keyword}"}
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

        return {"ignored_tool": name}
