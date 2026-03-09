"""Structured JSON logging helpers."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

try:  # pragma: no cover - optional dependency in minimal local envs
    from opentelemetry.trace import (  # type: ignore[import-not-found]
        format_span_id,
        format_trace_id,
        get_current_span,
    )
except Exception:  # pragma: no cover - fallback when opentelemetry is unavailable

    def get_current_span():  # type: ignore[no-redef]
        return None

    def format_trace_id(value: int) -> str:  # type: ignore[no-redef]
        return f"{value:032x}"

    def format_span_id(value: int) -> str:  # type: ignore[no-redef]
        return f"{value:016x}"


REQUEST_ID: ContextVar[str | None] = ContextVar("request_id", default=None)


def set_request_id(request_id: str) -> Token[str | None]:
    """Set request id in context for current execution flow."""
    return REQUEST_ID.set(request_id)


def clear_request_id(token: Token[str | None]) -> None:
    """Reset request id context to previous value."""
    REQUEST_ID.reset(token)


class JsonFormatter(logging.Formatter):
    """Format log records as JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialize one log record as JSON."""
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": REQUEST_ID.get(),
        }
        current_span = get_current_span()
        if current_span is not None:
            context = current_span.get_span_context()
            if getattr(context, "is_valid", False):
                payload["trace_id"] = format_trace_id(context.trace_id)
                payload["span_id"] = format_span_id(context.span_id)
        if hasattr(record, "event"):
            payload["event"] = record.event
        if hasattr(record, "context"):
            payload["context"] = record.context
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    """Configure root logger with JSON formatter."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
