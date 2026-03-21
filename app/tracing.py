"""Shared OpenTelemetry helpers.

Provides a no-op tracer/span that matches the OTel API surface so all modules
can import `get_tracer` and write instrumentation code without conditional
try/except blocks throughout the codebase.  When `opentelemetry` is installed
and a provider is configured, `get_tracer` returns a real tracer.
"""

from __future__ import annotations

from typing import Any, Literal


class NoopSpan:
    """Drop-in replacement for an OTel span when tracing is unavailable."""

    def __enter__(self) -> "NoopSpan":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Literal[False]:
        return False

    def set_attribute(self, _name: str, _value: object) -> None:
        return None

    def record_exception(self, _exc: BaseException) -> None:
        return None


class NoopTracer:
    """Drop-in replacement for an OTel tracer when tracing is unavailable."""

    def start_as_current_span(self, _name: str, **_kwargs: object) -> NoopSpan:
        return NoopSpan()


def get_tracer(module_name: str) -> Any:
    """Return a real OTel tracer if available, otherwise a NoopTracer.

    Usage::

        from app.tracing import get_tracer
        TRACER = get_tracer(__name__)

        with TRACER.start_as_current_span("my.operation") as span:
            span.set_attribute("key", "value")
    """
    try:
        from opentelemetry import trace  # type: ignore[import-not-found]

        return trace.get_tracer(module_name)
    except Exception:
        return NoopTracer()
