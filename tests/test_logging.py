"""JSON logging formatter tests."""

from __future__ import annotations

import json
import logging
import sys

from app.logging import JsonFormatter


def test_exc_info_present_for_exception_records() -> None:
    formatter = JsonFormatter()
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="failed",
            args=(),
            exc_info=sys.exc_info(),
        )

    payload = json.loads(formatter.format(record))
    assert "exc_info" in payload
    assert "ValueError: boom" in payload["exc_info"]


def test_exc_info_absent_for_info_records() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="ok",
        args=(),
        exc_info=None,
    )

    payload = json.loads(formatter.format(record))
    assert "exc_info" not in payload


def test_trace_and_span_ids_included_when_span_context_present(monkeypatch) -> None:
    formatter = JsonFormatter()

    class _SpanContext:
        is_valid = True
        trace_id = int("1" * 32, 16)
        span_id = int("2" * 16, 16)

    class _Span:
        def get_span_context(self):
            return _SpanContext()

    monkeypatch.setattr("app.logging.get_current_span", lambda: _Span())

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="ok",
        args=(),
        exc_info=None,
    )
    payload = json.loads(formatter.format(record))
    assert payload["trace_id"] == "11111111111111111111111111111111"
    assert payload["span_id"] == "2222222222222222"
