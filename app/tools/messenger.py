"""Messaging integration stubs."""

from __future__ import annotations


def send_reply(user_id: str | None, text: str) -> dict[str, str | None]:
    """Return a fake delivery object for MVP."""
    return {
        "delivery": "queued",
        "user_id": user_id,
        "text": text,
    }
