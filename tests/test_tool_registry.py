"""Tool registry behavior tests."""

from __future__ import annotations

from typing import get_type_hints

import fakeredis
import pytest

from app.agent import AgentService
from app.approval_store import RedisApprovalStore
from app.config import Settings
from app.schemas import ProposedAction
from app.store import EventStore
from app.tools import TOOL_REGISTRY, ToolHandler


class FakeLLMClient:
    def run_agent(self, text: str, user_id: str | None = None, max_turns: int = 5):
        raise AssertionError("not used")


def _agent() -> AgentService:
    settings = Settings()
    return AgentService(
        settings=settings,
        store=EventStore(sqlite_path=None),
        approval_store=RedisApprovalStore(fakeredis.FakeRedis(), ttl_seconds=3600),
        llm_client=FakeLLMClient(),
    )


def test_known_tool_dispatches() -> None:
    agent = _agent()
    action = ProposedAction(tool="create_ticket_and_reply", payload={"title": "t", "reply_to": "u1"})

    result = agent.execute_action(action, "u1", "hello")

    assert "ticket" in result
    assert "reply" in result


def test_unknown_tool_raises_value_error() -> None:
    agent = _agent()
    action = ProposedAction(tool="does_not_exist", payload={})

    with pytest.raises(ValueError):
        agent.execute_action(action, "u1", "hello")


def test_registry_annotation() -> None:
    hints = get_type_hints(__import__("app.tools", fromlist=["TOOL_REGISTRY"]))
    assert hints["TOOL_REGISTRY"] == dict[str, ToolHandler]
    assert isinstance(TOOL_REGISTRY, dict)
