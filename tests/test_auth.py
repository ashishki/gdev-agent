"""JWT middleware and auth dependency tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request
from fastapi.params import Depends
from fastapi.responses import JSONResponse
from jose import jwt

from app.config import Settings
from app.dependencies import require_role
from app.middleware.auth import JWTMiddleware


def _token(
    settings: Settings,
    *,
    tenant_id: str,
    user_id: str,
    role: str,
    jti: str,
    exp_delta_s: int,
) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=exp_delta_s)).timestamp()),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _request(
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    app_state: object | None = None,
) -> Request:
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


@pytest.mark.asyncio
async def test_valid_jwt_sets_request_state() -> None:
    settings = Settings()
    middleware = JWTMiddleware(app=None, settings=settings)
    tenant_id = str(uuid4())
    user_id = str(uuid4())
    jti = str(uuid4())
    token = _token(
        settings,
        tenant_id=tenant_id,
        user_id=user_id,
        role="support_agent",
        jti=jti,
        exp_delta_s=300,
    )
    redis_stub = SimpleNamespace(get=AsyncMock(return_value=None))
    request = _request(
        "POST",
        "/approve",
        headers={"Authorization": f"Bearer {token}"},
        app_state=SimpleNamespace(jwt_blocklist_redis=redis_stub),
    )
    captured: dict[str, object] = {}

    async def _ok(req: Request):
        captured["tenant_id"] = req.state.tenant_id
        captured["user_id"] = req.state.user_id
        captured["role"] = req.state.role
        return JSONResponse({"ok": True}, status_code=200)

    response = await middleware.dispatch(request, _ok)

    assert response.status_code == 200
    assert str(captured["tenant_id"]) == tenant_id
    assert str(captured["user_id"]) == user_id
    assert captured["role"] == "support_agent"
    redis_stub.get.assert_awaited_once_with(f"jwt:blocklist:{jti}")


@pytest.mark.asyncio
async def test_expired_jwt_returns_token_expired() -> None:
    settings = Settings()
    middleware = JWTMiddleware(app=None, settings=settings)
    token = _token(
        settings,
        tenant_id=str(uuid4()),
        user_id=str(uuid4()),
        role="viewer",
        jti=str(uuid4()),
        exp_delta_s=-60,
    )
    request = _request(
        "POST",
        "/approve",
        headers={"Authorization": f"Bearer {token}"},
        app_state=SimpleNamespace(jwt_blocklist_redis=SimpleNamespace(get=AsyncMock(return_value=None))),
    )

    response = await middleware.dispatch(request, lambda _: JSONResponse({"ok": True}, status_code=200))

    assert response.status_code == 401
    assert b'"code":"token_expired"' in response.body


@pytest.mark.asyncio
async def test_revoked_jwt_returns_401() -> None:
    settings = Settings()
    middleware = JWTMiddleware(app=None, settings=settings)
    jti = str(uuid4())
    token = _token(
        settings,
        tenant_id=str(uuid4()),
        user_id=str(uuid4()),
        role="viewer",
        jti=jti,
        exp_delta_s=300,
    )
    redis_stub = SimpleNamespace(get=AsyncMock(return_value=b"1"))
    request = _request(
        "POST",
        "/approve",
        headers={"Authorization": f"Bearer {token}"},
        app_state=SimpleNamespace(jwt_blocklist_redis=redis_stub),
    )

    response = await middleware.dispatch(request, lambda _: JSONResponse({"ok": True}, status_code=200))

    assert response.status_code == 401
    redis_stub.get.assert_awaited_once_with(f"jwt:blocklist:{jti}")


@pytest.mark.asyncio
async def test_redis_unavailable_during_blocklist_check_returns_503() -> None:
    settings = Settings()
    middleware = JWTMiddleware(app=None, settings=settings)
    token = _token(
        settings,
        tenant_id=str(uuid4()),
        user_id=str(uuid4()),
        role="viewer",
        jti=str(uuid4()),
        exp_delta_s=300,
    )
    redis_stub = SimpleNamespace(get=AsyncMock(side_effect=RuntimeError("redis down")))
    request = _request(
        "POST",
        "/approve",
        headers={"Authorization": f"Bearer {token}"},
        app_state=SimpleNamespace(jwt_blocklist_redis=redis_stub),
    )

    response = await middleware.dispatch(request, lambda _: JSONResponse({"ok": True}, status_code=200))

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_exempt_routes_do_not_require_jwt() -> None:
    settings = Settings()
    middleware = JWTMiddleware(app=None, settings=settings)
    routes = [("GET", "/health"), ("POST", "/webhook")]

    async def _ok(_: Request):
        return JSONResponse({"ok": True}, status_code=200)

    for method, path in routes:
        request = _request(method, path, app_state=SimpleNamespace())
        response = await middleware.dispatch(request, _ok)
        assert response.status_code == 200


def test_require_role_enforces_allowed_roles() -> None:
    dep = require_role("tenant_admin", "support_agent")
    assert isinstance(dep, Depends)

    request = SimpleNamespace(state=SimpleNamespace(role="viewer"))
    with pytest.raises(HTTPException) as exc:
        dep.dependency(request)
    assert exc.value.status_code == 403

    request_ok = SimpleNamespace(state=SimpleNamespace(role="support_agent"))
    dep.dependency(request_ok)
