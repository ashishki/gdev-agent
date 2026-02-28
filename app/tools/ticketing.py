"""Ticketing integration stubs."""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from app.config import Settings
from app.integrations.linear import LinearClient

LOGGER = logging.getLogger(__name__)
_PRIORITY_MAP = {"critical": 1, "high": 2, "medium": 3, "low": 4}


def create_ticket(payload: dict[str, Any]) -> dict[str, Any]:
    """Create support ticket via Linear when configured, otherwise fallback stub."""
    settings = Settings()
    if settings.linear_api_key and settings.linear_team_id:
        client = LinearClient(settings.linear_api_key)
        return client.create_issue(
            title=str(payload.get("title", "Support request")),
            description=str(payload.get("text", "")),
            priority=_PRIORITY_MAP.get(str(payload.get("urgency", "medium")), 3),
            team_id=settings.linear_team_id,
        )

    LOGGER.warning("linear disabled, using stub", extra={"event": "linear_stub_fallback", "context": {}})
    ticket_id = f"TKT-{uuid4().hex[:8].upper()}"
    return {
        "ticket_id": ticket_id,
        "title": payload.get("title", "Support request"),
        "status": "created",
    }
