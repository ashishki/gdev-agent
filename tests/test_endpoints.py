"""Tests for T11 read endpoints."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from jose import jwt

from app import main
from app.config import Settings
from app.middleware.auth import JWTMiddleware
from app.routers import auth as auth_module
from app.routers.agents import list_agents
from app.routers.analytics import list_audit, list_cost_metrics
from app.routers.clusters import get_cluster, get_cluster_tickets, list_clusters
from app.routers.eval import list_eval_runs
from app.routers.tickets import get_ticket, list_tickets
from app.services.auth_service import LogoutRequest, RefreshTokenRequest

UTC = timezone.utc


class _MetricChildStub:
    def __init__(self) -> None:
        self.increments: list[float] = []
        self.observations: list[float] = []

    def inc(self, value: float = 1.0) -> None:
        self.increments.append(value)

    def observe(self, value: float) -> None:
        self.observations.append(value)


class _MetricStub:
    def __init__(self) -> None:
        self.children: list[tuple[dict[str, object], _MetricChildStub]] = []

    def labels(self, **labels: object) -> _MetricChildStub:
        child = _MetricChildStub()
        self.children.append((labels, child))
        return child


class _SpanStub:
    def __init__(self, name: str) -> None:
        self.name = name
        self.attributes: dict[str, object] = {}
        self.exceptions: list[BaseException] = []

    def __enter__(self) -> "_SpanStub":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        return False

    def set_attribute(self, name: str, value: object) -> None:
        self.attributes[name] = value

    def record_exception(self, exc: BaseException) -> None:
        self.exceptions.append(exc)


class _TracerStub:
    def __init__(self) -> None:
        self.spans: list[_SpanStub] = []

    def start_as_current_span(self, name: str) -> _SpanStub:
        span = _SpanStub(name)
        self.spans.append(span)
        return span


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


class _SequencedSessionStub:
    def __init__(self, rows_by_call: list[list[dict[str, object]]]) -> None:
        self.rows_by_call = rows_by_call
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def execute(self, statement, params):  # noqa: ANN001
        self.calls.append((str(statement), params))
        rows = self.rows_by_call.pop(0) if self.rows_by_call else []
        return _ResultStub(rows)


def _request(tenant_id: UUID, role: str = "tenant_admin") -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(tenant_id=tenant_id, role=role))


class _AsyncRedisStub:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex: int) -> bool:
        self.values[key] = value
        return True


def _auth_request(app_state: object) -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=app_state))


def _http_request(
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    app_state: object | None = None,
):
    from fastapi import Request

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "path": path,
        "headers": [
            (key.lower().encode("latin-1"), value.encode("latin-1"))
            for key, value in (headers or {}).items()
        ],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "scheme": "http",
        "app": SimpleNamespace(state=app_state or SimpleNamespace()),
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


def _route_dependency(path: str) -> object:
    route = next(
        route
        for route in main.app.router.routes
        if getattr(route, "path", None) == path and "GET" in getattr(route, "methods", set())
    )
    dependencies = route.dependant.dependencies
    assert dependencies, f"Expected dependencies on {path}"
    role_dependency = next(
        (
            dependency.call
            for dependency in dependencies
            if getattr(dependency.call, "__name__", "") == "dependency"
        ),
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

    response = await list_cost_metrics(
        request=_request(tenant_id), cursor=None, limit=50, db=session
    )
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

    response = await list_cost_metrics(
        request=_request(tenant_id), cursor=None, limit=1, db=session
    )
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


@pytest.mark.asyncio
async def test_list_clusters_filters_active_and_severity() -> None:
    tenant_id = uuid4()
    now = datetime.now(UTC)
    session = _SessionStub(
        [
            {
                "cluster_id": uuid4(),
                "label": "Payment timeout",
                "summary": "Checkout failures",
                "ticket_count": 5,
                "severity": "high",
                "first_seen": now - timedelta(hours=1),
                "last_seen": now,
                "is_active": True,
                "updated_at": now,
            }
        ]
    )

    response = await list_clusters(
        request=_request(tenant_id),
        cursor=None,
        limit=50,
        is_active=True,
        severity="high",
        db=session,
    )

    assert response.data[0].label == "Payment timeout"
    assert session.last_params["tenant_id"] == str(tenant_id)
    assert session.last_params["is_active"] is True
    assert session.last_params["severity"] == "high"


@pytest.mark.asyncio
async def test_list_clusters_emits_span_and_counter(monkeypatch) -> None:
    from app.routers import clusters as clusters_module

    tracer = _TracerStub()
    counter = _MetricStub()
    histogram = _MetricStub()
    tenant_id = uuid4()
    now = datetime.now(UTC)
    session = _SessionStub(
        [
            {
                "cluster_id": uuid4(),
                "label": "Payment timeout",
                "summary": "Checkout failures",
                "ticket_count": 5,
                "severity": "high",
                "first_seen": now - timedelta(hours=1),
                "last_seen": now,
                "is_active": True,
                "updated_at": now,
            }
        ]
    )

    monkeypatch.setattr(clusters_module, "TRACER", tracer)
    monkeypatch.setattr(clusters_module, "CLUSTER_LIST_REQUESTS_TOTAL", counter)
    monkeypatch.setattr(clusters_module, "CLUSTER_LIST_DURATION_SECONDS", histogram)

    response = await list_clusters(
        request=_request(tenant_id),
        cursor=None,
        limit=50,
        is_active=True,
        severity="high",
        db=session,
    )

    assert response.data[0].label == "Payment timeout"
    assert tracer.spans[0].name == "router.clusters.list_clusters"
    assert "tenant_id_hash" in tracer.spans[0].attributes
    assert counter.children[0][0]["outcome"] == "success"
    assert counter.children[0][1].increments == [1.0]
    assert len(histogram.children[0][1].observations) == 1


@pytest.mark.asyncio
async def test_get_cluster_returns_ticket_ids_up_to_10() -> None:
    tenant_id = uuid4()
    cluster_id = uuid4()
    now = datetime.now(UTC)
    session = _SequencedSessionStub(
        [
            [
                {
                    "cluster_id": cluster_id,
                    "label": "Payment timeout",
                    "summary": "Checkout failures",
                    "ticket_count": 12,
                    "severity": "high",
                    "first_seen": now - timedelta(hours=1),
                    "last_seen": now,
                    "is_active": True,
                    "updated_at": now,
                }
            ],
            [{"ticket_id": uuid4()} for _ in range(12)],
        ]
    )

    response = await get_cluster(cluster_id=cluster_id, request=_request(tenant_id), db=session)

    assert len(response.data[0].ticket_ids) == 10
    assert str(response.data[0].cluster_id) == str(cluster_id)
    assert "FROM rca_cluster_members" in session.calls[1][0]
    assert "ticket_embeddings" not in session.calls[1][0]


@pytest.mark.asyncio
async def test_get_cluster_emits_span_and_counter(monkeypatch) -> None:
    from app.routers import clusters as clusters_module

    tracer = _TracerStub()
    counter = _MetricStub()
    histogram = _MetricStub()
    tenant_id = uuid4()
    cluster_id = uuid4()
    now = datetime.now(UTC)
    session = _SequencedSessionStub(
        [
            [
                {
                    "cluster_id": cluster_id,
                    "label": "Payment timeout",
                    "summary": "Checkout failures",
                    "ticket_count": 12,
                    "severity": "high",
                    "first_seen": now - timedelta(hours=1),
                    "last_seen": now,
                    "is_active": True,
                    "updated_at": now,
                }
            ],
            [{"ticket_id": uuid4()}],
        ]
    )

    monkeypatch.setattr(clusters_module, "TRACER", tracer)
    monkeypatch.setattr(clusters_module, "CLUSTER_DETAIL_REQUESTS_TOTAL", counter)
    monkeypatch.setattr(clusters_module, "CLUSTER_DETAIL_DURATION_SECONDS", histogram)

    response = await get_cluster(cluster_id=cluster_id, request=_request(tenant_id), db=session)

    assert str(response.data[0].cluster_id) == str(cluster_id)
    assert tracer.spans[0].name == "router.clusters.get_cluster"
    assert tracer.spans[0].attributes["cluster_id"] == str(cluster_id)
    assert counter.children[0][0]["outcome"] == "success"
    assert counter.children[0][1].increments == [1.0]
    assert len(histogram.children[0][1].observations) == 1


@pytest.mark.asyncio
async def test_get_cluster_cross_tenant_returns_404() -> None:
    session = _SequencedSessionStub([[]])
    response = await get_cluster(cluster_id=uuid4(), request=_request(uuid4()), db=session)
    assert isinstance(response, JSONResponse)
    assert response.status_code == 404
    assert b'"code":"cluster_not_found"' in response.body


@pytest.mark.asyncio
async def test_get_cluster_tickets_returns_paginated_payload() -> None:
    tenant_id = uuid4()
    cluster_id = uuid4()
    now = datetime.now(UTC)
    session = _SequencedSessionStub(
        [
            [{"cluster_id": cluster_id}],
            [{"total": 2}],
            [
                {
                    "ticket_id": uuid4(),
                    "message_id": "m1",
                    "platform": "telegram",
                    "game_title": "G1",
                    "created_at": now,
                }
            ],
        ]
    )

    response = await get_cluster_tickets(
        cluster_id=cluster_id,
        request=_request(tenant_id),
        page=2,
        limit=1,
        db=session,
    )

    assert response.total == 2
    assert response.page == 2
    assert response.tickets[0].message_id == "m1"
    assert "FROM rca_cluster_members AS m" in session.calls[2][0]
    assert session.calls[2][1]["offset"] == 1


@pytest.mark.asyncio
async def test_get_cluster_tickets_cross_tenant_returns_404() -> None:
    session = _SequencedSessionStub([[]])

    response = await get_cluster_tickets(
        cluster_id=uuid4(),
        request=_request(uuid4()),
        page=1,
        limit=50,
        db=session,
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 404
    assert b'"code":"cluster_not_found"' in response.body


def test_wrong_role_is_rejected_for_tenant_admin_endpoints() -> None:
    for path in ("/audit", "/metrics/cost", "/agents"):
        dependency = _route_dependency(path)
        with pytest.raises(HTTPException) as exc:
            dependency(SimpleNamespace(state=SimpleNamespace(role="viewer")))
        assert exc.value.status_code == 403


def test_cluster_tickets_requires_viewer_role() -> None:
    dependency = _route_dependency("/clusters/{cluster_id}/tickets")

    with pytest.raises(HTTPException) as exc:
        dependency(SimpleNamespace(state=SimpleNamespace(role="operator")))

    assert exc.value.status_code == 403


def test_reader_roles_allowed_for_jwt_read_endpoints() -> None:
    for path in (
        "/tickets",
        "/tickets/{ticket_id}",
        "/eval/runs",
        "/clusters",
        "/clusters/{cluster_id}",
        "/clusters/{cluster_id}/tickets",
    ):
        dependency = _route_dependency(path)
        dependency(SimpleNamespace(state=SimpleNamespace(role="viewer")))
        dependency(SimpleNamespace(state=SimpleNamespace(role="support_agent")))
        dependency(SimpleNamespace(state=SimpleNamespace(role="tenant_admin")))


@pytest.mark.asyncio
async def test_auth_logout_revokes_token_for_next_request() -> None:
    settings = Settings(jwt_secret="x" * 32)
    redis_stub = _AsyncRedisStub()
    tenant_id = str(uuid4())
    user_id = str(uuid4())
    jti = str(uuid4())
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": user_id,
            "tenant_id": tenant_id,
            "role": "viewer",
            "jti": jti,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    app_state = SimpleNamespace(
        settings=settings,
        db_session_factory=object(),
        jwt_blocklist_redis=redis_stub,
    )

    response = await auth_module.logout(
        LogoutRequest(access_token=token),
        _auth_request(app_state),
    )

    assert response.status == "revoked"

    middleware = JWTMiddleware(app=None, settings=settings)
    protected_request = _http_request(
        "GET",
        "/tickets",
        headers={"Authorization": f"Bearer {token}"},
        app_state=SimpleNamespace(jwt_blocklist_redis=redis_stub, settings=settings),
    )
    blocked = await middleware.dispatch(
        protected_request, lambda _: JSONResponse({"ok": True}, status_code=200)
    )

    assert blocked.status_code == 401


@pytest.mark.asyncio
async def test_auth_refresh_returns_new_access_token() -> None:
    settings = Settings(jwt_secret="x" * 32, jwt_token_expiry_hours=8)
    redis_stub = _AsyncRedisStub()
    tenant_id = str(uuid4())
    user_id = str(uuid4())
    old_jti = str(uuid4())
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": user_id,
            "tenant_id": tenant_id,
            "role": "tenant_admin",
            "jti": old_jti,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    app_state = SimpleNamespace(
        settings=settings,
        db_session_factory=object(),
        jwt_blocklist_redis=redis_stub,
    )

    response = await auth_module.refresh_token(
        RefreshTokenRequest(access_token=token),
        _auth_request(app_state),
    )

    claims = jwt.decode(
        response.access_token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )
    assert claims["sub"] == user_id
    assert claims["tenant_id"] == tenant_id
    assert claims["role"] == "tenant_admin"
    assert claims["jti"] != old_jti
