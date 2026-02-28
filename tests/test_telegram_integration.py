"""Telegram integration tests."""

from __future__ import annotations

from unittest.mock import Mock, patch

from app.integrations.telegram import TelegramClient


@patch("app.integrations.telegram.httpx.Client")
def test_send_message_success(mock_client_cls) -> None:
    mock_client = mock_client_cls.return_value.__enter__.return_value
    response = Mock(status_code=200)
    response.json.return_value = {"result": {"message_id": 123}}
    response.raise_for_status.return_value = None
    mock_client.post.return_value = response

    result = TelegramClient("token").send_message("chat1", "hello")
    assert result["delivery"] == "sent"
    assert result["message_id"] == 123


@patch("app.integrations.telegram.httpx.Client")
def test_send_approval_request_callback_data(mock_client_cls) -> None:
    mock_client = mock_client_cls.return_value.__enter__.return_value
    response = Mock(status_code=200)
    response.json.return_value = {"result": {"message_id": 321}}
    response.raise_for_status.return_value = None
    mock_client.post.return_value = response

    message_id = TelegramClient("token").send_approval_request(
        chat_id="ops",
        pending_id="a" * 32,
        draft="draft",
        category="billing",
        urgency="high",
        reason="manual",
    )

    assert message_id == "321"
    payload = mock_client.post.call_args.kwargs["json"]
    buttons = payload["reply_markup"]["inline_keyboard"][0]
    assert buttons[0]["callback_data"] == f"approve:{'a'*32}"
    assert buttons[1]["callback_data"] == f"reject:{'a'*32}"


@patch("app.integrations.telegram.httpx.Client")
def test_telegram_429_does_not_raise(mock_client_cls) -> None:
    mock_client = mock_client_cls.return_value.__enter__.return_value
    response = Mock(status_code=429)
    mock_client.post.return_value = response

    result = TelegramClient("token").send_message("chat1", "hello")
    assert result["delivery"] == "queued"
