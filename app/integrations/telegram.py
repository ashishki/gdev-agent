"""Telegram Bot API integration."""

from __future__ import annotations

import logging
from typing import Any

import httpx

LOGGER = logging.getLogger(__name__)


class TelegramClient:
    """Simple Telegram sender client."""

    def __init__(self, token: str) -> None:
        self.base_url = f"https://api.telegram.org/bot{token}"

    def send_message(self, chat_id: str, text: str) -> dict[str, Any]:
        """Send plain Telegram message."""
        with httpx.Client(timeout=10.0) as client:
            response = client.post(f"{self.base_url}/sendMessage", json={"chat_id": chat_id, "text": text})
        if response.status_code == 429:
            LOGGER.warning("telegram throttled", extra={"event": "telegram_throttled", "context": {}})
            return {"delivery": "queued"}
        response.raise_for_status()
        data = response.json().get("result", {})
        return {"delivery": "sent", "message_id": data.get("message_id")}

    def send_approval_request(
        self,
        chat_id: str,
        pending_id: str,
        draft: str,
        category: str,
        urgency: str,
        reason: str,
    ) -> str:
        """Send approval message with inline approve/reject callbacks."""
        text = (
            "Approval required\n"
            f"Category: {category}\n"
            f"Urgency: {urgency}\n"
            f"Reason: {reason}\n\n"
            f"Draft:\n{draft}"
        )
        markup = {
            "inline_keyboard": [
                [
                    {"text": "✅ Approve", "callback_data": f"approve:{pending_id}"},
                    {"text": "❌ Reject", "callback_data": f"reject:{pending_id}"},
                ]
            ]
        }
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                f"{self.base_url}/sendMessage",
                json={"chat_id": chat_id, "text": text, "reply_markup": markup},
            )
        if response.status_code == 429:
            LOGGER.warning("telegram throttled", extra={"event": "telegram_throttled", "context": {}})
            return ""
        response.raise_for_status()
        data = response.json().get("result", {})
        return str(data.get("message_id", ""))

