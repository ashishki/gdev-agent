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

    got = client._create_message(model="m", max_tokens=1, system="s", tools=[], tool_choice={}, messages=[])

    assert got is response
    assert create_mock.call_count == 2


def test_create_message_does_not_retry_429() -> None:
    create_mock = Mock(side_effect=FakeAPIStatusError(429))
    client = _client_with_create(create_mock)

    with pytest.raises(FakeAPIStatusError):
        client._create_message(model="m", max_tokens=1, system="s", tools=[], tool_choice={}, messages=[])

    assert create_mock.call_count == 1
