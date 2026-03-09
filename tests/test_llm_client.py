"""LLM client retry policy tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.config import Settings
from app.llm_client import LLMClient


class FakeAPIStatusError(Exception):
    def __init__(self, status_code: int):
        super().__init__(f"status={status_code}")
        self.status_code = status_code


def _client_with_create(create_mock: Mock) -> LLMClient:
    client = object.__new__(LLMClient)
    client.settings = Settings(anthropic_api_key="test-key")
    client._anthropic = SimpleNamespace(APIStatusError=FakeAPIStatusError)
    client._client = SimpleNamespace(messages=SimpleNamespace(create=create_mock))
    client._retry_sleep = lambda _: None
    return client


def test_create_message_retries_5xx_then_succeeds() -> None:
    response = object()
    create_mock = Mock(side_effect=[FakeAPIStatusError(500), response])
    client = _client_with_create(create_mock)

    got = client._create_message(
        model="m", max_tokens=1, system="s", tools=[], tool_choice={}, messages=[]
    )

    assert got is response
    assert create_mock.call_count == 2


def test_create_message_does_not_retry_429() -> None:
    create_mock = Mock(side_effect=FakeAPIStatusError(429))
    client = _client_with_create(create_mock)

    with pytest.raises(FakeAPIStatusError):
        client._create_message(
            model="m", max_tokens=1, system="s", tools=[], tool_choice={}, messages=[]
        )

    assert create_mock.call_count == 1


def test_lookup_faq_uses_configured_kb_base_url() -> None:
    client = object.__new__(LLMClient)
    client.settings = Settings(
        anthropic_api_key="test-key", kb_base_url="https://support.mygame.com"
    )

    result = client._dispatch_tool(
        "lookup_faq", {"keywords": ["billing", "refund"]}, user_id="u1"
    )

    urls = [article["url"] for article in result["articles"]]
    assert urls == [
        "https://support.mygame.com/billing",
        "https://support.mygame.com/refund",
    ]


def test_classify_tool_invalid_category_falls_back_to_safe_default(caplog) -> None:
    client = object.__new__(LLMClient)
    client.settings = Settings(anthropic_api_key="test-key")

    with caplog.at_level("ERROR"):
        result = client._dispatch_tool(
            "classify_request",
            {"category": "made_up", "urgency": "low", "confidence": 0.7},
            user_id="u1",
        )

    assert result["category"] == "other"
    assert result["confidence"] == 0.0
    assert any(
        getattr(r, "event", None) == "llm_invalid_response" for r in caplog.records
    )


def test_classify_tool_clamps_confidence_and_logs_warning(caplog) -> None:
    client = object.__new__(LLMClient)
    client.settings = Settings(anthropic_api_key="test-key")

    with caplog.at_level("WARNING"):
        result = client._dispatch_tool(
            "classify_request",
            {"category": "other", "urgency": "low", "confidence": 9.9},
            user_id="u1",
        )

    assert result["confidence"] == 1.0
    assert any(
        getattr(r, "event", None) == "llm_invalid_response"
        and r.context.get("reason") == "confidence_clamped"
        for r in caplog.records
    )


def test_unknown_tool_sets_force_pending_marker_and_logs(caplog) -> None:
    client = object.__new__(LLMClient)
    client.settings = Settings(anthropic_api_key="test-key")

    with caplog.at_level("WARNING"):
        result = client._dispatch_tool("unknown_tool", {"x": 1}, user_id="u1")

    assert result["__force_pending__"] is True
    assert any(getattr(r, "event", None) == "llm_unknown_tool" for r in caplog.records)
