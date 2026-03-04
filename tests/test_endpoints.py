"""Tests for T11 read endpoints."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from app import main
from app.routers.agents import list_agents
from app.routers.analytics import list_audit, list_cost_metrics, list_eval_runs
from app.routers.tickets import get_ticket, list_tickets


class _ResultStub:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self) -> "_ResultStub":
        return self

    def all(self) -> list[dict[str, object]]:
        return self._rows

    def first(self) -> dict[str, object] | None:
        if not self._rows:
            return None
        return self._rows[0]


class _SessionStub:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.last_statement = ""
        self.last_params: dict[str, object] = {}

    async def execute(self, statement, params):  # noqa: ANN001
        self.last_statement = str(statement)
        self.last_params = params
        return _ResultStub(self.rows)


def _request(tenant_id: UUID, role: str = "tenant_admin") -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(tenant_id=tenant_id, role=role))


def _route_dependency(path: str) -> object:
    route = next(
        route
        for route in main.app.router.routes
        if getattr(route, "path", None) == path and "GET" in getattr(route, "methods", set())
    )
    dependencies = route.dependant.dependencies
    assert dependencies, f"Expected dependencies on {path}"
    role_dependency = next(
        (dependency.call for dependency in dependencies if getattr(dependency.call, "__name__", "") == "dependency"),
        None,
    )
    assert role_dependency is not None, f"Expected role dependency on {path}"
    return role_dependency


@pytest.mark.asyncio
async def test_list_tickets_happy_path() -> None:
    tenant_id = uuid4()
    now = datetime.now(UTC)
    session = _SessionStub(
        [
            {
                "ticket_id": uuid4(),
                "message_id": "m1",
                "platform": "telegram",
                "game_title": "G1",
                "created_at": now,
            }
        ]
    )

    response = await list_tickets(request=_request(tenant_id), cursor=None, limit=50, db=session)

    assert response.data[0].message_id == "m1"
    assert response.cursor is None
    assert response.total is None
    assert session.last_params["tenant_id"] == str(tenant_id)


@pytest.mark.asyncio
async def test_list_tickets_pagination_sets_cursor() -> None:
    tenant_id = uuid4()
    now = datetime.now(UTC)
    session = _SessionStub(
        [
            {
                "ticket_id": uuid4(),
                "message_id": "m1",
                "platform": "telegram",
                "game_title": "G1",
                "created_at": now,
            },
            {
                "ticket_id": uuid4(),
                "message_id": "m2",
                "platform": "telegram",
                "game_title": "G2",
                "created_at": now - timedelta(minutes=1),
            },
        ]
    )

    response = await list_tickets(request=_request(tenant_id), cursor=None, limit=1, db=session)

    assert len(response.data) == 1
    assert response.cursor is not None


@pytest.mark.asyncio
async def test_get_ticket_cross_tenant_returns_404() -> None:
    session = _SessionStub([])
    response = await get_ticket(ticket_id=uuid4(), request=_request(uuid4()), db=session)
    assert isinstance(response, JSONResponse)
    assert response.status_code == 404
    assert b'"code":"ticket_not_found"' in response.body


@pytest.mark.asyncio
async def test_list_audit_happy_path_newest_first_query() -> None:
    tenant_id = uuid4()
    now = datetime.now(UTC)
    session = _SessionStub(
        [
            {
                "audit_id": uuid4(),
                "request_id": "r1",
                "message_id": "m1",
                "category": "billing",
                "urgency": "high",
                "confidence": Decimal("0.900"),
                "action_tool": "create_ticket_and_reply",
                "status": "executed",
                "ticket_id": uuid4(),
                "latency_ms": 120,
                "input_tokens": 10,
                "output_tokens": 20,
                "cost_usd": Decimal("0.1234"),
                "created_at": now,
            }
        ]
    )

    response = await list_audit(request=_request(tenant_id), cursor=None, limit=50, db=session)

    assert response.data[0].request_id == "r1"
    assert "ORDER BY created_at DESC" in session.last_statement


@pytest.mark.asyncio
async def test_list_audit_pagination_sets_cursor() -> None:
    tenant_id = uuid4()
    now = datetime.now(UTC)
    session = _SessionStub(
        [
            {
                "audit_id": uuid4(),
                "request_id": "r1",
                "message_id": "m1",
                "category": "billing",
                "urgency": "high",
                "confidence": Decimal("0.900"),
                "action_tool": "create_ticket_and_reply",
                "status": "executed",
                "ticket_id": uuid4(),
                "latency_ms": 120,
                "input_tokens": 10,
                "output_tokens": 20,
                "cost_usd": Decimal("0.1234"),
                "created_at": now,
            },
            {
                "audit_id": uuid4(),
                "request_id": "r2",
                "message_id": "m2",
                "category": "billing",
                "urgency": "high",
                "confidence": Decimal("0.900"),
                "action_tool": "create_ticket_and_reply",
                "status": "executed",
                "ticket_id": uuid4(),
                "latency_ms": 120,
                "input_tokens": 10,
                "output_tokens": 20,
                "cost_usd": Decimal("0.1234"),
                "created_at": now - timedelta(minutes=1),
            },
        ]
    )

    response = await list_audit(request=_request(tenant_id), cursor=None, limit=1, db=session)
    assert response.cursor is not None


@pytest.mark.asyncio
async def test_list_cost_metrics_happy_path() -> None:
    tenant_id = uuid4()
    session = _SessionStub(
        [
            {
                "ledger_id": uuid4(),
                "date": date.today(),
                "input_tokens": 5,
                "output_tokens": 8,
                "cost_usd": Decimal("0.1111"),
                "request_count": 2,
                "created_at": datetime.now(UTC),
            }
        ]
    )

    response = await list_cost_metrics(request=_request(tenant_id), cursor=None, limit=50, db=session)
    assert response.data[0].request_count == 2


@pytest.mark.asyncio
async def test_list_cost_metrics_pagination_sets_cursor() -> None:
    tenant_id = uuid4()
    now = datetime.now(UTC)
    session = _SessionStub(
        [
            {
                "ledger_id": uuid4(),
                "date": date.today(),
                "input_tokens": 5,
                "output_tokens": 8,
                "cost_usd": Decimal("0.1111"),
                "request_count": 2,
                "created_at": now,
            },
            {
                "ledger_id": uuid4(),
                "date": date.today(),
                "input_tokens": 1,
                "output_tokens": 2,
                "cost_usd": Decimal("0.0010"),
                "request_count": 1,
                "created_at": now - timedelta(minutes=1),
            },
        ]
    )

    response = await list_cost_metrics(request=_request(tenant_id), cursor=None, limit=1, db=session)
    assert response.cursor is not None


@pytest.mark.asyncio
async def test_list_agents_happy_path() -> None:
    tenant_id = uuid4()
    session = _SessionStub(
        [
            {
                "agent_config_id": uuid4(),
                "agent_name": "triage",
                "version": 2,
                "model_id": "claude-sonnet",
                "max_turns": 5,
                "tools_enabled": ["create_ticket_and_reply"],
                "guardrails": {"max_len": 2000},
                "prompt_version": "v1",
                "is_current": True,
                "created_at": datetime.now(UTC),
            }
        ]
    )

    response = await list_agents(request=_request(tenant_id), cursor=None, limit=50, db=session)
    assert response.data[0].agent_name == "triage"


@pytest.mark.asyncio
async def test_list_agents_pagination_sets_cursor() -> None:
    tenant_id = uuid4()
    now = datetime.now(UTC)
    session = _SessionStub(
        [
            {
                "agent_config_id": uuid4(),
                "agent_name": "triage",
                "version": 2,
                "model_id": "claude-sonnet",
                "max_turns": 5,
                "tools_enabled": ["create_ticket_and_reply"],
                "guardrails": {"max_len": 2000},
                "prompt_version": "v1",
                "is_current": True,
                "created_at": now,
            },
            {
                "agent_config_id": uuid4(),
                "agent_name": "triage",
                "version": 1,
                "model_id": "claude-sonnet",
                "max_turns": 5,
                "tools_enabled": ["create_ticket_and_reply"],
                "guardrails": {"max_len": 2000},
                "prompt_version": "v0",
                "is_current": False,
                "created_at": now - timedelta(minutes=1),
            },
        ]
    )

    response = await list_agents(request=_request(tenant_id), cursor=None, limit=1, db=session)
    assert response.cursor is not None


@pytest.mark.asyncio
async def test_list_eval_runs_happy_path() -> None:
    tenant_id = uuid4()
    session = _SessionStub(
        [
            {
                "eval_run_id": uuid4(),
                "started_at": datetime.now(UTC),
                "completed_at": datetime.now(UTC),
                "f1_score": Decimal("0.920"),
                "guard_block_rate": Decimal("1.000"),
                "cost_usd": Decimal("0.2000"),
                "status": "completed",
                "created_at": datetime.now(UTC),
            }
        ]
    )

    response = await list_eval_runs(request=_request(tenant_id), cursor=None, limit=50, db=session)
    assert response.data[0].status == "completed"


@pytest.mark.asyncio
async def test_list_eval_runs_pagination_sets_cursor() -> None:
    tenant_id = uuid4()
    now = datetime.now(UTC)
    session = _SessionStub(
        [
            {
                "eval_run_id": uuid4(),
                "started_at": now,
                "completed_at": now,
                "f1_score": Decimal("0.920"),
                "guard_block_rate": Decimal("1.000"),
                "cost_usd": Decimal("0.2000"),
                "status": "completed",
                "created_at": now,
            },
            {
                "eval_run_id": uuid4(),
                "started_at": now - timedelta(minutes=1),
                "completed_at": now - timedelta(minutes=1),
                "f1_score": Decimal("0.900"),
                "guard_block_rate": Decimal("1.000"),
                "cost_usd": Decimal("0.2100"),
                "status": "completed",
                "created_at": now - timedelta(minutes=1),
            },
        ]
    )

    response = await list_eval_runs(request=_request(tenant_id), cursor=None, limit=1, db=session)
    assert response.cursor is not None


def test_wrong_role_is_rejected_for_tenant_admin_endpoints() -> None:
    for path in ("/audit", "/metrics/cost", "/agents"):
        dependency = _route_dependency(path)
        with pytest.raises(HTTPException) as exc:
            dependency(SimpleNamespace(state=SimpleNamespace(role="viewer")))
        assert exc.value.status_code == 403


def test_reader_roles_allowed_for_jwt_read_endpoints() -> None:
    for path in ("/tickets", "/tickets/{ticket_id}", "/eval/runs"):
        dependency = _route_dependency(path)
        dependency(SimpleNamespace(state=SimpleNamespace(role="viewer")))
        dependency(SimpleNamespace(state=SimpleNamespace(role="support_agent")))
        dependency(SimpleNamespace(state=SimpleNamespace(role="tenant_admin")))
