"""Tool registry and handlers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, TypeAlias

from app.tools.messenger import send_reply
from app.tools.ticketing import create_ticket

ToolHandler: TypeAlias = Callable[[dict[str, Any], str | None], dict[str, Any]]
ToolSideEffect: TypeAlias = Literal["read", "write", "bulk_write", "destructive"]


@dataclass(frozen=True)
class ToolSpec:
    """Runtime tool metadata used by safety gates."""

    handler: ToolHandler
    side_effect: ToolSideEffect
    approval_required: bool = False
    description: str = ""
    audit_label: str | None = None


def _create_ticket_and_reply(payload: dict[str, Any], user_id: str | None) -> dict[str, Any]:
    """Create ticket and send reply using existing stubs/integrations."""
    ticket = create_ticket(payload)
    reply_text = str(payload.get("draft_response", ""))
    reply_target = (
        str(payload.get("reply_to") or user_id) if (payload.get("reply_to") or user_id) else None
    )
    reply = send_reply(reply_target, reply_text)
    return {"ticket": ticket, "reply": reply}


TOOL_REGISTRY: dict[str, ToolSpec] = {
    "create_ticket_and_reply": ToolSpec(
        handler=_create_ticket_and_reply,
        side_effect="write",
        approval_required=False,
        description="Create a support ticket and send the drafted reply.",
        audit_label="ticket_reply",
    ),
}
