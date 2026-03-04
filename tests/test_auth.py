"""JWT middleware and auth dependency tests."""

from __future__ import annotations

import hashlib
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
from app.middleware.rate_limit import RateLimitMiddleware
from app.routers import auth as auth_module
from app.schemas import AuthTokenRequest, AuthTokenResponse


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
    routes = [("GET", "/health"), ("POST", "/webhook"), ("POST", "/auth/token")]

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


class _ResultStub:
    def __init__(self, row: dict[str, object] | None) -> None:
        self._row = row

    def mappings(self) -> "_ResultStub":
        return self

    def first(self) -> dict[str, object] | None:
        return self._row


class _SessionStub:
    def __init__(
        self,
        row: dict[str, object] | None,
        execute_calls: list[tuple[str, dict[str, object]]],
        known_tenant_slug: str = "tenant-a",
    ) -> None:
        self._row = row
        self._execute_calls = execute_calls
        self._known_tenant_slug = known_tenant_slug
        self._tenant_context_valid = False

    async def __aenter__(self) -> "_SessionStub":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def begin(self):
        return self

    async def execute(self, statement, params):
        self._execute_calls.append((str(statement), params))
        sql = str(statement).lower()
        if "set_config(" in sql:
            self._tenant_context_valid = params.get("tenant_slug") == self._known_tenant_slug
            return _ResultStub({"set_config": "ok"})
        if "from tenant_users" in sql and self._tenant_context_valid:
            return _ResultStub(self._row)
        return _ResultStub(None)


class _SessionFactoryStub:
    def __init__(self, row: dict[str, object] | None, known_tenant_slug: str = "tenant-a") -> None:
        self._row = row
        self._known_tenant_slug = known_tenant_slug
        self.execute_calls: list[tuple[str, dict[str, object]]] = []

    def __call__(self) -> _SessionStub:
        return _SessionStub(self._row, self.execute_calls, self._known_tenant_slug)


def _auth_request(
    row: dict[str, object] | None,
    settings: Settings | None = None,
    known_tenant_slug: str = "tenant-a",
) -> Request:
    session_factory = _SessionFactoryStub(row, known_tenant_slug=known_tenant_slug)
    state = SimpleNamespace(
        settings=settings or Settings(jwt_secret="x" * 32, jwt_token_expiry_hours=8),
        db_session_factory=session_factory,
    )
    return _request("POST", "/auth/token", app_state=state)


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
async def test_auth_token_correct_credentials_returns_jwt(monkeypatch) -> None:
    password = "s3cret!"
    user_id = str(uuid4())
    tenant_id = str(uuid4())
    settings = Settings(jwt_secret="x" * 32, jwt_token_expiry_hours=8)
    row = {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "role": "support_agent",
        "password_hash": "stored-hash",
    }
    monkeypatch.setattr(auth_module.bcrypt, "checkpw", lambda candidate, stored: (
        candidate == password.encode("utf-8") and stored == b"stored-hash"
    ))
    request = _auth_request(row, settings=settings, known_tenant_slug="tenant-a")
    response = await auth_module.create_auth_token(
        AuthTokenRequest(tenant_slug="tenant-a", email="agent@example.com", password=password),
        request,
    )

    assert isinstance(response, AuthTokenResponse)
    body = response.model_dump()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 8 * 3600
    claims = jwt.decode(body["access_token"], settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    assert claims["sub"] == user_id
    assert claims["tenant_id"] == tenant_id
    assert claims["role"] == "support_agent"
    execute_calls = request.app.state.db_session_factory.execute_calls
    assert len(execute_calls) == 2
    assert "set_config" in execute_calls[0][0].lower()
    assert execute_calls[0][1] == {"tenant_slug": "tenant-a"}


@pytest.mark.asyncio
async def test_auth_token_wrong_password_returns_401_and_logs_hashed_email(monkeypatch) -> None:
    from unittest.mock import Mock

    warning = Mock()
    monkeypatch.setattr(auth_module.LOGGER, "warning", warning)
    monkeypatch.setattr(auth_module.bcrypt, "checkpw", lambda *_: False)
    row = {
        "user_id": str(uuid4()),
        "tenant_id": str(uuid4()),
        "role": "viewer",
        "password_hash": "stored-hash",
    }
    response = await auth_module.create_auth_token(
        AuthTokenRequest(
            tenant_slug="tenant-a",
            email="viewer@example.com",
            password="wrong-password",
        ),
        _auth_request(row, known_tenant_slug="tenant-a"),
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 401
    assert b'"code":"invalid_credentials"' in response.body
    warning.assert_called_once()
    context = warning.call_args.kwargs["extra"]["context"]
    assert context["email_hash"] == auth_module.hashlib.sha256(
        b"viewer@example.com"
    ).hexdigest()


@pytest.mark.asyncio
async def test_auth_token_unknown_email_returns_same_401_shape(monkeypatch) -> None:
    monkeypatch.setattr(auth_module.bcrypt, "checkpw", lambda *_: False)
    response = await auth_module.create_auth_token(
        AuthTokenRequest(tenant_slug="tenant-a", email="missing@example.com", password="pw"),
        _auth_request(None, known_tenant_slug="tenant-a"),
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 401
    assert (
        response.body
        == b'{"error":{"code":"invalid_credentials","message":"Invalid email or password"}}'
    )


@pytest.mark.asyncio
async def test_auth_token_rate_limit_blocks_after_5_attempts() -> None:
    middleware = RateLimitMiddleware(
        app=None,
        settings=Settings(auth_rate_limit_attempts=5),
        redis_client=_AsyncRedisStub(),
    )

    async def unauthorized(_request):
        return JSONResponse(
            {"error": {"code": "invalid_credentials", "message": "Invalid email or password"}},
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
    seen: list[tuple[bytes, bytes]] = []

    def _spy(password: bytes, hashed: bytes) -> bool:
        seen.append((password, hashed))
        return True

    monkeypatch.setattr(auth_module.bcrypt, "checkpw", _spy)
    row = {
        "user_id": str(uuid4()),
        "tenant_id": str(uuid4()),
        "role": "viewer",
        "password_hash": "stored-hash",
    }
    response = await auth_module.create_auth_token(
        AuthTokenRequest(tenant_slug="tenant-a", email="user@example.com", password="pw"),
        _auth_request(row, known_tenant_slug="tenant-a"),
    )

    assert isinstance(response, AuthTokenResponse)
    assert seen


@pytest.mark.asyncio
async def test_auth_token_unknown_tenant_slug_returns_401(monkeypatch) -> None:
    monkeypatch.setattr(auth_module.bcrypt, "checkpw", lambda *_: False)
    row = {
        "user_id": str(uuid4()),
        "tenant_id": str(uuid4()),
        "role": "viewer",
        "password_hash": "stored-hash",
    }
    response = await auth_module.create_auth_token(
        AuthTokenRequest(tenant_slug="tenant-x", email="user@example.com", password="pw"),
        _auth_request(row, known_tenant_slug="tenant-a"),
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == 401


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
            {"error": {"code": "invalid_credentials", "message": "Invalid email or password"}},
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
            {"error": {"code": "invalid_credentials", "message": "Invalid email or password"}},
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
