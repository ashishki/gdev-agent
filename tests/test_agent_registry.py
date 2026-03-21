"""Tests for agent registry update flow (T12)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import main
from app.agent_registry import AgentConfigNotFoundError, AgentRegistryService
from app.routers import agents as agents_router
from app.schemas import AgentConfigUpdate

UTC = timezone.utc

class _ResultStub:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self) -> "_ResultStub":
        return self

    def first(self) -> dict[str, object] | None:
        if not self._rows:
            return None
        return self._rows[0]

    def one(self) -> dict[str, object]:
        if not self._rows:
            raise AssertionError("Expected one row")
        return self._rows[0]


class _SessionStub:
    def __init__(self, responses: list[list[dict[str, object]]]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def execute(self, statement, params):  # noqa: ANN001
        self.calls.append((str(statement), params))
        if not self._responses:
            raise AssertionError("No queued DB response")
        rows = self._responses.pop(0)
        return _ResultStub(rows)


def _role_dependency_for_put_agents():
    route = next(
        route
        for route in main.app.router.routes
        if getattr(route, "path", None) == "/agents/{agent_id}"
        and "PUT" in getattr(route, "methods", set())
    )
    role_dependency = next(
        (
            dependency.call
            for dependency in route.dependant.dependencies
            if dependency.call.__name__ == "dependency"
        ),
        None,
    )
    assert role_dependency is not None
    return role_dependency


@pytest.mark.asyncio
async def test_update_config_version_bump() -> None:
    service = AgentRegistryService()
    tenant_id = uuid4()
    old_agent_config_id = uuid4()
    created_at = datetime.now(UTC)
    session = _SessionStub(
        responses=[
            [{"agent_config_id": old_agent_config_id, "version": 2}],
            [{}],
            [
                {
                    "agent_config_id": uuid4(),
                    "agent_name": "triage",
                    "version": 3,
                    "model_id": "claude-sonnet",
                    "max_turns": 6,
                    "tools_enabled": ["create_ticket_and_reply"],
                    "guardrails": {"max_len": 2000},
                    "prompt_version": "v2",
                    "is_current": True,
                    "created_at": created_at,
                }
            ],
        ]
    )
    payload = AgentConfigUpdate(
        agent_name="triage",
        model_id="claude-sonnet",
        max_turns=6,
        tools_enabled=["create_ticket_and_reply"],
        guardrails={"max_len": 2000},
        prompt_version="v2",
    )

    response = await service.update_config(
        tenant_id=tenant_id,
        agent_config_id=old_agent_config_id,
        payload=payload,
        db=session,
    )

    assert response.version == 3
    assert any("UPDATE agent_configs" in call[0] for call in session.calls)
    insert_params = session.calls[2][1]
    assert insert_params["version"] == 3
    assert insert_params["tenant_id"] == str(tenant_id)


@pytest.mark.asyncio
async def test_update_config_cross_tenant_rejected() -> None:
    service = AgentRegistryService()
    session = _SessionStub(responses=[[]])
    payload = AgentConfigUpdate(
        agent_name="triage",
        model_id="claude-sonnet",
        max_turns=6,
        tools_enabled=["create_ticket_and_reply"],
        guardrails={"max_len": 2000},
        prompt_version="v2",
    )

    with pytest.raises(AgentConfigNotFoundError):
        await service.update_config(
            tenant_id=uuid4(),
            agent_config_id=uuid4(),
            payload=payload,
            db=session,
        )


@pytest.mark.asyncio
async def test_put_agents_route_returns_404_for_missing_or_cross_tenant(
    monkeypatch,
) -> None:
    class _ServiceStub:
        async def update_config(self, **_kwargs):  # noqa: ANN003
            raise AgentConfigNotFoundError("missing")

    monkeypatch.setattr(agents_router, "_agent_registry_service", _ServiceStub())
    invalidate_calls = []

    async def _invalidate(_tenant_id):
        invalidate_calls.append(_tenant_id)

    request = SimpleNamespace(
        state=SimpleNamespace(tenant_id=uuid4()),
        app=SimpleNamespace(
            state=SimpleNamespace(
                tenant_registry=SimpleNamespace(invalidate=_invalidate)
            )
        ),
    )

    response = await agents_router.update_agent(
        agent_id=uuid4(),
        payload=AgentConfigUpdate(
            agent_name="triage",
            model_id="claude-sonnet",
            max_turns=6,
            tools_enabled=["create_ticket_and_reply"],
            guardrails={"max_len": 2000},
            prompt_version="v2",
        ),
        request=request,
        db=SimpleNamespace(),
    )

    assert response.status_code == 404
    assert not invalidate_calls


def test_put_agents_requires_tenant_admin_role() -> None:
    dependency = _role_dependency_for_put_agents()
    with pytest.raises(HTTPException) as exc:
        dependency(SimpleNamespace(state=SimpleNamespace(role="viewer")))
    assert exc.value.status_code == 403


def test_agent_config_update_payload_validation() -> None:
    with pytest.raises(ValidationError):
        AgentConfigUpdate.model_validate(
            {
                "agent_name": "",
                "model_id": "claude-sonnet",
                "max_turns": 0,
                "tools_enabled": [],
                "guardrails": {},
                "prompt_version": "",
            }
        )
