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
