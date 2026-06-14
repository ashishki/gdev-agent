"""RBAC tests for role enforcement on /approve."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from jose import jwt

from app import main
from app.config import Settings
from app.middleware.auth import JWTMiddleware
from app.schemas import ApproveRequest

UTC = timezone.utc


def _approve_role_dependency():
    route = next(
        r
        for r in main.app.router.routes
        if getattr(r, "path", None) == "/approve" and "POST" in getattr(r, "methods", set())
    )
    dependencies = route.dependant.dependencies
    assert dependencies, "Expected at least one dependency on /approve"
    return dependencies[0].call


def _route_role_dependency(path: str, method: str = "GET"):
    route = next(
        r
        for r in main.app.router.routes
        if getattr(r, "path", None) == path and method in getattr(r, "methods", set())
    )
    dependency = next(
        (
            dependency.call
            for dependency in route.dependant.dependencies
            if getattr(dependency.call, "__name__", "") == "dependency"
        ),
        None,
    )
    assert dependency is not None, f"Expected role dependency on {path}"
    return dependency


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


class _AsyncRedisStub:
    async def get(self, _key: str) -> str | None:
        return None


def test_viewer_role_cannot_call_approve() -> None:
    dependency = _approve_role_dependency()
    request = SimpleNamespace(state=SimpleNamespace(role="viewer"))
    with pytest.raises(HTTPException) as exc:
        dependency(request)
    assert exc.value.status_code == 403


def test_support_agent_role_can_call_approve() -> None:
    dependency = _approve_role_dependency()
    dependency(SimpleNamespace(state=SimpleNamespace(role="support_agent")))

    main.app.state.settings = Settings(anthropic_api_key="k", approve_secret="approve-secret")
    main.app.state.agent = SimpleNamespace(
        approve=lambda _payload, jwt_tenant_id=None: {
            "status": "approved",
            "pending_id": "p1",
            "result": {"ok": True},
        }
    )
    response = main.approve(
        ApproveRequest(pending_id="p1", approved=True),
        request=SimpleNamespace(
            headers={"X-Approve-Secret": "approve-secret"},
            state=SimpleNamespace(tenant_id="tenant-a"),
        ),
    )
    assert response["status"] == "approved"


def test_tenant_admin_role_can_call_approve() -> None:
    dependency = _approve_role_dependency()
    dependency(SimpleNamespace(state=SimpleNamespace(role="tenant_admin")))

    main.app.state.settings = Settings(anthropic_api_key="k", approve_secret="approve-secret")
    main.app.state.agent = SimpleNamespace(
        approve=lambda _payload, jwt_tenant_id=None: {
            "status": "approved",
            "pending_id": "p1",
            "result": {"ok": True},
        }
    )
    response = main.approve(
        ApproveRequest(pending_id="p1", approved=True),
        request=SimpleNamespace(
            headers={"X-Approve-Secret": "approve-secret"},
            state=SimpleNamespace(tenant_id="tenant-a"),
        ),
    )
    assert response["status"] == "approved"


def test_tenant_read_routes_require_jwt_reader_roles() -> None:
    for path in (
        "/tickets",
        "/tickets/{ticket_id}",
        "/audit",
        "/metrics/cost",
        "/metrics/learning",
        "/agents",
        "/eval/runs",
        "/clusters",
        "/clusters/{cluster_id}",
        "/clusters/{cluster_id}/tickets",
    ):
        dependency = _route_role_dependency(path)
        with pytest.raises(HTTPException):
            dependency(SimpleNamespace(state=SimpleNamespace(role=None)))


@pytest.mark.asyncio
async def test_tenant_read_api_rejects_jwt_without_tenant_claim() -> None:
    settings = Settings(jwt_secret="x" * 32)
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "role": "viewer",
            "jti": str(uuid4()),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    middleware = JWTMiddleware(app=None, settings=settings)
    request = _http_request(
        "GET",
        "/tickets",
        headers={"Authorization": "Bearer" + " " + token},
        app_state=SimpleNamespace(jwt_blocklist_redis=_AsyncRedisStub(), settings=settings),
    )

    response = await middleware.dispatch(request, lambda _: JSONResponse({"ok": True}))

    assert response.status_code == 401
