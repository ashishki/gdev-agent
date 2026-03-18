"""Signature and rate limit middleware tests."""

from __future__ import annotations

import hashlib
import hmac
from types import SimpleNamespace
from uuid import UUID, uuid5

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse

from app.config import Settings
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.signature import SignatureMiddleware
from app.secrets_store import WebhookSecretNotFoundError
from app.tenant_registry import TenantNotFoundError


class _SecretStoreStub:
    def __init__(self, secrets_by_slug: dict[str, str]) -> None:
        self._secrets_by_slug = secrets_by_slug

    async def get_secret_by_slug(self, tenant_slug: str) -> str:
        if tenant_slug == "unknown":
            raise TenantNotFoundError("missing")
        secret = self._secrets_by_slug.get(tenant_slug)
        if secret is None:
            raise WebhookSecretNotFoundError("missing")
        return secret

    async def get_secret_and_tenant_by_slug(self, tenant_slug: str) -> tuple[UUID, str]:
        secret = await self.get_secret_by_slug(tenant_slug)
        return uuid5(UUID("00000000-0000-0000-0000-000000000000"), tenant_slug), secret


class _AsyncRedisStub:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.expire_calls: list[tuple[str, int]] = []
        self.incr_calls: list[str] = []

    async def incr(self, key: str) -> int:
        self.incr_calls.append(key)
        value = self.values.get(key, 0) + 1
        self.values[key] = value
        return value

    async def expire(self, key: str, seconds: int) -> int:
        self.expire_calls.append((key, seconds))
        return 1


def _sig(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _scope(
    path: str, headers: dict[str, str], app_state: object | None = None
) -> dict[str, object]:
    scope_app = (
        SimpleNamespace(state=app_state)
        if app_state is not None
        else SimpleNamespace(state=SimpleNamespace())
    )
    return {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": path,
        "headers": [
            (k.lower().encode("latin-1"), v.encode("latin-1"))
            for k, v in headers.items()
        ],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "scheme": "http",
        "app": scope_app,
    }


async def _run_signature(
    middleware: SignatureMiddleware,
    body: bytes,
    headers: dict[str, str],
    app_state: object,
) -> tuple[int, bool]:
    sent: list[dict[str, object]] = []
    called = {"downstream": False}

    async def receive():
        if receive.sent:
            return {"type": "http.disconnect"}
        receive.sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    receive.sent = False  # type: ignore[attr-defined]

    async def send(message):
        sent.append(message)

    async def downstream(scope, receive, send):
        called["downstream"] = True
        await JSONResponse({"ok": True}, status_code=200)(scope, receive, send)

    middleware.app = downstream
    scope = _scope("/webhook", headers, app_state=app_state)
    await middleware(scope, receive, send)

    status = next(msg["status"] for msg in sent if msg["type"] == "http.response.start")
    return int(status), called["downstream"]


@pytest.mark.asyncio
async def test_missing_tenant_slug_rejected() -> None:
    middleware = SignatureMiddleware(app=None, settings=Settings())
    status, called = await _run_signature(
        middleware,
        b'{"user_id":"u1","text":"hi"}',
        {"X-Webhook-Signature": "sha256=x"},
        app_state=SimpleNamespace(
            webhook_secret_store=_SecretStoreStub({"tenant-a": "secret-a"})
        ),
    )
    assert status == 400
    assert called is False


@pytest.mark.asyncio
async def test_correct_signature_passes() -> None:
    middleware = SignatureMiddleware(app=None, settings=Settings())
    body = b'{"user_id":"u1","text":"hi"}'
    status, called = await _run_signature(
        middleware,
        body,
        {
            "X-Tenant-Slug": "tenant-a",
            "X-Webhook-Signature": _sig("secret-a", body),
            "Content-Type": "application/json",
        },
        app_state=SimpleNamespace(
            webhook_secret_store=_SecretStoreStub({"tenant-a": "secret-a"})
        ),
    )
    assert status == 200
    assert called is True


@pytest.mark.asyncio
async def test_tampered_body_with_old_signature_rejected() -> None:
    middleware = SignatureMiddleware(app=None, settings=Settings())
    original = b'{"user_id":"u1","text":"hi"}'
    tampered = b'{"user_id":"u1","text":"bye"}'
    status, called = await _run_signature(
        middleware,
        tampered,
        {
            "X-Tenant-Slug": "tenant-a",
            "X-Webhook-Signature": _sig("secret-a", original),
            "Content-Type": "application/json",
        },
        app_state=SimpleNamespace(
            webhook_secret_store=_SecretStoreStub({"tenant-a": "secret-a"})
        ),
    )
    assert status == 401
    assert called is False


@pytest.mark.asyncio
async def test_unknown_tenant_slug_rejected() -> None:
    middleware = SignatureMiddleware(app=None, settings=Settings())
    body = b'{"user_id":"u1","text":"hi"}'
    status, called = await _run_signature(
        middleware,
        body,
        {
            "X-Tenant-Slug": "unknown",
            "X-Webhook-Signature": _sig("secret-a", body),
            "Content-Type": "application/json",
        },
        app_state=SimpleNamespace(
            webhook_secret_store=_SecretStoreStub({"tenant-a": "secret-a"})
        ),
    )
    assert status == 401
    assert called is False


@pytest.mark.asyncio
async def test_cross_tenant_secret_rejected() -> None:
    middleware = SignatureMiddleware(app=None, settings=Settings())
    body = b'{"user_id":"u1","text":"hi"}'
    status, called = await _run_signature(
        middleware,
        body,
        {
            "X-Tenant-Slug": "tenant-b",
            "X-Webhook-Signature": _sig("secret-a", body),
            "Content-Type": "application/json",
        },
        app_state=SimpleNamespace(
            webhook_secret_store=_SecretStoreStub(
                {"tenant-a": "secret-a", "tenant-b": "secret-b"}
            )
        ),
    )
    assert status == 401
    assert called is False


def _request(
    body: bytes, path: str = "/webhook", app_state: object | None = None
) -> Request:
    scope = _scope(path, {"Content-Type": "application/json"}, app_state=app_state)

    async def receive():
        if receive.sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        receive.sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    receive.sent = False  # type: ignore[attr-defined]
    return Request(scope, receive)


@pytest.mark.asyncio
async def test_rate_limit_exceeded_for_same_user() -> None:
    redis_client = _AsyncRedisStub()
    middleware = RateLimitMiddleware(
        app=None,
        settings=Settings(rate_limit_rpm=2, rate_limit_burst=10),
        redis_client=redis_client,
    )

    async def ok(_request):
        return JSONResponse({"ok": True}, status_code=200)

    request = _request(b'{"user_id":"u1","text":"hi"}')
    request.state.tenant_id = "tenant-a"
    assert (await middleware.dispatch(request, ok)).status_code == 200
    request = _request(b'{"user_id":"u1","text":"hi"}')
    request.state.tenant_id = "tenant-a"
    assert (await middleware.dispatch(request, ok)).status_code == 200
    request = _request(b'{"user_id":"u1","text":"hi"}')
    request.state.tenant_id = "tenant-a"
    blocked = await middleware.dispatch(request, ok)
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "60"
    assert redis_client.incr_calls.count("tenant-a:ratelimit:u1") == 3
    assert ("tenant-a:ratelimit:u1", 60) in redis_client.expire_calls


@pytest.mark.asyncio
async def test_rate_limits_are_independent_per_user() -> None:
    redis_client = _AsyncRedisStub()
    middleware = RateLimitMiddleware(
        app=None,
        settings=Settings(rate_limit_rpm=1, rate_limit_burst=10),
        redis_client=redis_client,
    )

    async def ok(_request):
        return JSONResponse({"ok": True}, status_code=200)

    request = _request(b'{"user_id":"u1","text":"hi"}')
    request.state.tenant_id = "tenant-a"
    assert (await middleware.dispatch(request, ok)).status_code == 200
    request = _request(b'{"user_id":"u2","text":"hi"}')
    request.state.tenant_id = "tenant-a"
    assert (await middleware.dispatch(request, ok)).status_code == 200
    assert "tenant-a:ratelimit:u1" in redis_client.incr_calls
    assert "tenant-a:ratelimit:u2" in redis_client.incr_calls


@pytest.mark.asyncio
async def test_burst_limit_exceeded_for_same_user() -> None:
    redis_client = _AsyncRedisStub()
    middleware = RateLimitMiddleware(
        app=None,
        settings=Settings(rate_limit_rpm=100, rate_limit_burst=3),
        redis_client=redis_client,
    )

    async def ok(_request):
        return JSONResponse({"ok": True}, status_code=200)

    request = _request(b'{"user_id":"u1","text":"hi"}')
    request.state.tenant_id = "tenant-a"
    assert (await middleware.dispatch(request, ok)).status_code == 200
    request = _request(b'{"user_id":"u1","text":"hi"}')
    request.state.tenant_id = "tenant-a"
    assert (await middleware.dispatch(request, ok)).status_code == 200
    request = _request(b'{"user_id":"u1","text":"hi"}')
    request.state.tenant_id = "tenant-a"
    assert (await middleware.dispatch(request, ok)).status_code == 200
    request = _request(b'{"user_id":"u1","text":"hi"}')
    request.state.tenant_id = "tenant-a"
    blocked = await middleware.dispatch(request, ok)
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "60"
    assert redis_client.incr_calls.count("tenant-a:ratelimit_burst:u1") == 4


@pytest.mark.asyncio
async def test_rate_limiter_uses_app_state_client_when_not_injected() -> None:
    redis_client = _AsyncRedisStub()
    middleware = RateLimitMiddleware(
        app=None, settings=Settings(rate_limit_rpm=1, rate_limit_burst=10)
    )

    async def ok(_request):
        return JSONResponse({"ok": True}, status_code=200)

    req = _request(
        b'{"user_id":"u1","text":"hi"}',
        app_state=SimpleNamespace(jwt_blocklist_redis=redis_client),
    )
    req.state.tenant_id = "tenant-a"
    assert (await middleware.dispatch(req, ok)).status_code == 200
    assert redis_client.incr_calls == [
        "tenant-a:ratelimit:u1",
        "tenant-a:ratelimit_burst:u1",
    ]


@pytest.mark.asyncio
async def test_rate_limiter_uses_anonymous_namespace_without_tenant_id() -> None:
    redis_client = _AsyncRedisStub()
    middleware = RateLimitMiddleware(
        app=None,
        settings=Settings(rate_limit_rpm=1, rate_limit_burst=10),
        redis_client=redis_client,
    )

    async def ok(_request):
        return JSONResponse({"ok": True}, status_code=200)

    assert (
        await middleware.dispatch(_request(b'{"user_id":"u1","text":"hi"}'), ok)
    ).status_code == 200
    assert redis_client.incr_calls == [
        "anonymous:ratelimit:u1",
        "anonymous:ratelimit_burst:u1",
    ]


def test_webhook_key_uses_tenant_first_order() -> None:
    assert (
        RateLimitMiddleware._webhook_key("ratelimit", "tenant-a", "u1")
        == "tenant-a:ratelimit:u1"
    )
    assert (
        RateLimitMiddleware._webhook_key("ratelimit", None, "u1")
        == "anonymous:ratelimit:u1"
    )
