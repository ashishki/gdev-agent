"""Messaging integration stubs."""

from __future__ import annotations

import logging

from app.config import Settings
from app.integrations.telegram import TelegramClient

LOGGER = logging.getLogger(__name__)


def send_reply(user_id: str | None, text: str) -> dict[str, str | None | int]:
    """Send Telegram reply when configured, otherwise return stub."""
    settings = Settings()
    if settings.telegram_bot_token and user_id:
        client = TelegramClient(settings.telegram_bot_token)
        try:
            return client.send_message(user_id, text)
        except Exception:
            LOGGER.warning("telegram send failed", extra={"event": "telegram_send_failed", "context": {}})
            return {"delivery": "queued", "user_id": user_id}

    if not settings.telegram_bot_token:
        LOGGER.warning("telegram disabled, using stub", extra={"event": "telegram_stub_fallback", "context": {}})
    return {
        "delivery": "queued",
        "user_id": user_id,
        "text": text,
    }
