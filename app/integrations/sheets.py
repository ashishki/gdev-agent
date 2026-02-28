"""Google Sheets audit logging integration."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.schemas import AuditLogEntry

LOGGER = logging.getLogger(__name__)


class SheetsClient:
    """Append-only Sheets client."""

    def __init__(self, credentials_json: str | None, spreadsheet_id: str | None) -> None:
        self.enabled = bool(credentials_json and spreadsheet_id)
        self.spreadsheet_id = spreadsheet_id
        self._service: Any | None = None
        if not self.enabled:
            LOGGER.warning("sheets disabled", extra={"event": "sheets_disabled", "context": {}})
            return
        try:
            from google.oauth2.service_account import Credentials  # type: ignore
            from googleapiclient.discovery import build  # type: ignore
        except Exception:
            self.enabled = False
            LOGGER.warning("sheets dependencies missing", extra={"event": "sheets_disabled", "context": {}})
            return

        creds_info = json.loads(credentials_json or "{}")
        creds = Credentials.from_service_account_info(
            creds_info,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        self._service = build("sheets", "v4", credentials=creds, cache_discovery=False)

    def append_log(self, entry: AuditLogEntry) -> None:
        """Append one audit row. Retries 429 twice with 60s delay."""
        if not self.enabled or not self._service or not self.spreadsheet_id:
            return
        values = [[
            entry.timestamp,
            entry.request_id,
            entry.message_id,
            entry.user_id,
            entry.category,
            entry.urgency,
            entry.confidence,
            entry.action,
            entry.status,
            entry.approved_by,
            entry.ticket_id,
            entry.latency_ms,
            entry.cost_usd,
        ]]

        for attempt in range(3):
            try:
                self._service.spreadsheets().values().append(
                    spreadsheetId=self.spreadsheet_id,
                    range="A:M",
                    valueInputOption="RAW",
                    body={"values": values},
                ).execute()
                return
            except Exception as exc:  # pragma: no cover - integration behavior
                status = getattr(exc, "status_code", None)
                if status == 429 and attempt < 2:
                    time.sleep(60)
                    continue
                LOGGER.warning(
                    "sheets append failed",
                    extra={"event": "sheets_append_failed", "context": {"attempt": attempt + 1}},
                )
                return

