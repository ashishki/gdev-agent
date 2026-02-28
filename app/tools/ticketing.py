"""Ticketing integration stubs."""

from __future__ import annotations

from typing import Any
from uuid import uuid4


def create_ticket(payload: dict[str, Any]) -> dict[str, Any]:
    """Create a fake ticket record for MVP."""
    ticket_id = f"TKT-{uuid4().hex[:8].upper()}"
    return {
        "ticket_id": ticket_id,
        "title": payload.get("title", "Support request"),
        "status": "created",
    }
