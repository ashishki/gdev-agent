"""Tool registry and handlers."""

from __future__ import annotations

from typing import Any, Callable, TypeAlias

from app.tools.messenger import send_reply
from app.tools.ticketing import create_ticket

ToolHandler: TypeAlias = Callable[[dict[str, Any], str | None], dict[str, Any]]


def _create_ticket_and_reply(payload: dict[str, Any], user_id: str | None) -> dict[str, Any]:
    """Create ticket and send reply using existing stubs/integrations."""
    ticket = create_ticket(payload)
    reply_text = str(payload.get("draft_response", ""))
    reply_target = str(payload.get("reply_to") or user_id) if (payload.get("reply_to") or user_id) else None
    reply = send_reply(reply_target, reply_text)
    return {"ticket": ticket, "reply": reply}


TOOL_REGISTRY: dict[str, ToolHandler] = {
    "create_ticket_and_reply": _create_ticket_and_reply,
}
