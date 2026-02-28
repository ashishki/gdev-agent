"""Sheets integration tests."""

from __future__ import annotations

from unittest.mock import Mock

from app.integrations.sheets import SheetsClient
from app.schemas import AuditLogEntry


def _entry() -> AuditLogEntry:
    return AuditLogEntry(
        timestamp="2026-01-01T00:00:00+00:00",
        request_id="r1",
        message_id="m1",
        user_id="hash",
        category="billing",
        urgency="high",
        confidence=0.9,
        action="create_ticket_and_reply",
        status="executed",
        approved_by="auto",
        ticket_id="ENG-1",
        latency_ms=10,
        cost_usd=0.0,
    )


def test_missing_credentials_disables_client() -> None:
    client = SheetsClient(None, None)
    assert client.enabled is False
    client.append_log(_entry())


def test_append_log_calls_api_when_enabled() -> None:
    client = SheetsClient(None, None)
    client.enabled = True
    client.spreadsheet_id = "sheet"

    service = Mock()
    client._service = service
    service.spreadsheets.return_value.values.return_value.append.return_value.execute.return_value = {}

    client.append_log(_entry())

    assert service.spreadsheets.return_value.values.return_value.append.called
