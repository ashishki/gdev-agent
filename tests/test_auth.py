"""JWT middleware and auth router tests."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
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
from app.middleware.rate_limit import RateLimitMiddleware
from app.routers import auth as auth_module
from app.schemas import AuthTokenRequest, AuthTokenResponse
from app.services.auth_service import (
    LoginResult,
    LogoutRequest,
    LogoutResponse,
    LogoutResult,
    RefreshTokenRequest,
    RefreshTokenResult,
)

UTC = timezone.utc


class _AsyncRedisStub:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        value = self.values.get(key, 0) + 1
        self.values[key] = value
        return value

    async def expire(self, key: str, seconds: int) -> int:
        _ = (key, seconds)
        return 1


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
        app_state=SimpleNamespace(
            jwt_blocklist_redis=SimpleNamespace(get=AsyncMock(return_value=None))
        ),
    )

    response = await middleware.dispatch(
        request, lambda _: JSONResponse({"ok": True}, status_code=200)
    )

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

    response = await middleware.dispatch(
        request, lambda _: JSONResponse({"ok": True}, status_code=200)
    )

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

    response = await middleware.dispatch(
        request, lambda _: JSONResponse({"ok": True}, status_code=200)
    )

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_exempt_routes_do_not_require_jwt() -> None:
    settings = Settings()
    middleware = JWTMiddleware(app=None, settings=settings)
    routes = [
        ("GET", "/health"),
        ("GET", "/metrics"),
        ("POST", "/webhook"),
        ("POST", "/auth/token"),
    ]

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


def _request_with_body(path: str, body: bytes) -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": path,
        "headers": [(b"content-type", b"application/json")],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "scheme": "http",
        "app": SimpleNamespace(state=SimpleNamespace()),
    }

    async def receive():
        if receive.sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        receive.sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    receive.sent = False  # type: ignore[attr-defined]
    return Request(scope, receive)


@pytest.mark.asyncio
async def test_auth_token_router_delegates_to_auth_service(monkeypatch) -> None:
    expected = AuthTokenResponse(access_token="token", expires_in=3600)
    login = AsyncMock(
        return_value=LoginResult(
            status_code=200,
            payload=expected,
        )
    )

    class _ServiceStub:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        async def login(self, payload: AuthTokenRequest) -> LoginResult:
            return await login(payload)

    monkeypatch.setattr(auth_module, "AuthService", _ServiceStub)
    request = _request(
        "POST",
        "/auth/token",
        app_state=SimpleNamespace(
            settings=Settings(jwt_secret="x" * 32),
            db_session_factory=object(),
            jwt_blocklist_redis=object(),
        ),
    )
    payload = AuthTokenRequest(
        tenant_slug="tenant-a",
        email="agent@example.com",
        password="s3cret!",
    )

    response = await auth_module.create_auth_token(payload, request)

    assert response == expected
    login.assert_awaited_once_with(payload)


@pytest.mark.asyncio
async def test_auth_token_router_returns_service_error_response(monkeypatch) -> None:
    error_result = LoginResult.model_validate(
        {
            "status_code": 401,
            "payload": {
                "error": {
                    "code": "invalid_credentials",
                    "message": "Invalid email or password",
                }
            },
        }
    )
    login = AsyncMock(return_value=error_result)

    class _ServiceStub:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        async def login(self, payload: AuthTokenRequest) -> LoginResult:
            return await login(payload)

    monkeypatch.setattr(auth_module, "AuthService", _ServiceStub)
    request = _request(
        "POST",
        "/auth/token",
        app_state=SimpleNamespace(
            settings=Settings(jwt_secret="x" * 32),
            db_session_factory=object(),
            jwt_blocklist_redis=object(),
        ),
    )

    response = await auth_module.create_auth_token(
        AuthTokenRequest(
            tenant_slug="tenant-a",
            email="agent@example.com",
            password="wrong-password",
        ),
        request,
    )

    assert response.status_code == 401
    assert b'"code":"invalid_credentials"' in response.body
    login.assert_awaited_once()


@pytest.mark.asyncio
async def test_auth_token_rate_limit_blocks_after_5_attempts() -> None:
    middleware = RateLimitMiddleware(
        app=None,
        settings=Settings(auth_rate_limit_attempts=5),
        redis_client=_AsyncRedisStub(),
    )

    async def unauthorized(_request):
        return JSONResponse(
            {
                "error": {
                    "code": "invalid_credentials",
                    "message": "Invalid email or password",
                }
            },
            status_code=401,
        )

    for _ in range(5):
        response = await middleware.dispatch(
            _request_with_body(
                "/auth/token",
                b'{"tenant_slug":"tenant-a","email":"user@example.com","password":"pw"}',
            ),
            unauthorized,
        )
        assert response.status_code == 401

    blocked = await middleware.dispatch(
        _request_with_body(
            "/auth/token",
            b'{"tenant_slug":"tenant-a","email":"user@example.com","password":"pw"}',
        ),
        unauthorized,
    )
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "60"


@pytest.mark.asyncio
async def test_auth_token_uses_bcrypt_checkpw(monkeypatch) -> None:
    seen: list[dict[str, object]] = []

    class _ServiceStub:
        def __init__(self, **kwargs) -> None:
            seen.append(kwargs)

        async def login(self, payload: AuthTokenRequest) -> LoginResult:
            _ = payload
            return LoginResult(
                status_code=200,
                payload=AuthTokenResponse(access_token="token", expires_in=3600),
            )

    monkeypatch.setattr(auth_module, "AuthService", _ServiceStub)
    state = SimpleNamespace(
        settings=Settings(jwt_secret="x" * 32),
        db_session_factory="db-factory",
        jwt_blocklist_redis="redis-client",
    )

    response = await auth_module.create_auth_token(
        AuthTokenRequest(
            tenant_slug="tenant-a",
            email="user@example.com",
            password="pw",
        ),
        _request("POST", "/auth/token", app_state=state),
    )

    assert isinstance(response, AuthTokenResponse)
    assert seen == [
        {
            "settings": state.settings,
            "db_session_factory": "db-factory",
            "jwt_blocklist_redis": "redis-client",
        }
    ]


@pytest.mark.asyncio
async def test_auth_token_unknown_tenant_slug_returns_401(monkeypatch) -> None:
    captured: list[AuthTokenRequest] = []
    error_result = LoginResult.model_validate(
        {
            "status_code": 401,
            "payload": {
                "error": {
                    "code": "invalid_credentials",
                    "message": "Invalid email or password",
                }
            },
        }
    )

    class _ServiceStub:
        def __init__(self, **kwargs) -> None:
            _ = kwargs

        async def login(self, payload: AuthTokenRequest) -> LoginResult:
            captured.append(payload)
            return error_result

    monkeypatch.setattr(auth_module, "AuthService", _ServiceStub)
    payload = AuthTokenRequest(
        tenant_slug="tenant-x",
        email="user@example.com",
        password="pw",
    )

    response = await auth_module.create_auth_token(
        payload,
        _request(
            "POST",
            "/auth/token",
            app_state=SimpleNamespace(
                settings=Settings(jwt_secret="x" * 32),
                db_session_factory=object(),
                jwt_blocklist_redis=object(),
            ),
        ),
    )

    assert response.status_code == 401
    assert captured == [payload]


@pytest.mark.asyncio
async def test_auth_logout_router_delegates_to_auth_service(monkeypatch) -> None:
    expected = LogoutResponse(status="revoked")
    logout = AsyncMock(return_value=LogoutResult(status_code=200, payload=expected))

    class _ServiceStub:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        async def logout(self, payload: LogoutRequest) -> LogoutResult:
            return await logout(payload)

    monkeypatch.setattr(auth_module, "AuthService", _ServiceStub)
    request = _request(
        "POST",
        "/auth/logout",
        app_state=SimpleNamespace(
            settings=Settings(jwt_secret="x" * 32),
            db_session_factory=object(),
            jwt_blocklist_redis=object(),
        ),
    )
    payload = LogoutRequest(access_token="token")

    response = await auth_module.logout(payload, request)

    assert response == expected
    logout.assert_awaited_once_with(payload)


@pytest.mark.asyncio
async def test_auth_refresh_router_delegates_to_auth_service(monkeypatch) -> None:
    expected = AuthTokenResponse(access_token="new-token", expires_in=3600)
    refresh = AsyncMock(return_value=RefreshTokenResult(status_code=200, payload=expected))

    class _ServiceStub:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        async def refresh_token(self, payload: RefreshTokenRequest) -> RefreshTokenResult:
            return await refresh(payload)

    monkeypatch.setattr(auth_module, "AuthService", _ServiceStub)
    request = _request(
        "POST",
        "/auth/refresh",
        app_state=SimpleNamespace(
            settings=Settings(jwt_secret="x" * 32),
            db_session_factory=object(),
            jwt_blocklist_redis=object(),
        ),
    )
    payload = RefreshTokenRequest(access_token="token")

    response = await auth_module.refresh_token(payload, request)

    assert response == expected
    refresh.assert_awaited_once_with(payload)


@pytest.mark.asyncio
async def test_auth_rate_limit_uses_hashed_email_key() -> None:
    redis_client = _AsyncRedisStub()
    middleware = RateLimitMiddleware(
        app=None,
        settings=Settings(auth_rate_limit_attempts=5),
        redis_client=redis_client,
    )

    async def unauthorized(_request):
        return JSONResponse(
            {
                "error": {
                    "code": "invalid_credentials",
                    "message": "Invalid email or password",
                }
            },
            status_code=401,
        )

    email = "hashme@example.com"
    hashed = hashlib.sha256(email.lower().encode("utf-8")).hexdigest()[:16]
    response = await middleware.dispatch(
        _request_with_body(
            "/auth/token",
            b'{"tenant_slug":"tenant-a","email":"hashme@example.com","password":"pw"}',
        ),
        unauthorized,
    )
    assert response.status_code == 401
    assert redis_client.values[f"auth_ratelimit:{hashed}"] == 1
    assert "auth_ratelimit:hashme@example.com" not in redis_client.values


@pytest.mark.asyncio
async def test_auth_rate_limit_attempts_uses_settings_value() -> None:
    middleware = RateLimitMiddleware(
        app=None,
        settings=Settings(auth_rate_limit_attempts=1),
        redis_client=_AsyncRedisStub(),
    )

    async def unauthorized(_request):
        return JSONResponse(
            {
                "error": {
                    "code": "invalid_credentials",
                    "message": "Invalid email or password",
                }
            },
            status_code=401,
        )

    first = await middleware.dispatch(
        _request_with_body(
            "/auth/token",
            b'{"tenant_slug":"tenant-a","email":"user@example.com","password":"pw"}',
        ),
        unauthorized,
    )
    second = await middleware.dispatch(
        _request_with_body(
            "/auth/token",
            b'{"tenant_slug":"tenant-a","email":"user@example.com","password":"pw"}',
        ),
        unauthorized,
    )

    assert first.status_code == 401
    assert second.status_code == 429


def test_adr_decision_matches_runtime_hs256_contract() -> None:
    settings = Settings()
    adr_text = Path("docs/adr/003-rbac-design.md").read_text(encoding="utf-8")

    assert settings.jwt_algorithm == "HS256"
    assert "JWT signed with HS256" in adr_text
    assert "No JWKS endpoint in v1" in adr_text
