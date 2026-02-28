"""Signature and rate limit middleware tests."""

from __future__ import annotations

import hashlib
import hmac

import fakeredis
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.signature import SignatureMiddleware


def _build_app(secret: str | None = None, rpm: int = 10) -> FastAPI:
    app = FastAPI()
    settings = Settings(webhook_secret=secret, rate_limit_rpm=rpm)
    app.add_middleware(RateLimitMiddleware, settings=settings, redis_client=fakeredis.FakeRedis())
    app.add_middleware(SignatureMiddleware, settings=settings)

    @app.post("/webhook")
    async def webhook(payload: dict):
        return {"ok": True, "user_id": payload.get("user_id")}

    return app


def _sig(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_missing_signature_rejected_when_secret_set() -> None:
    client = TestClient(_build_app(secret="secret"))
    res = client.post("/webhook", json={"user_id": "u1", "text": "hi"})
    assert res.status_code == 401


def test_correct_signature_passes() -> None:
    client = TestClient(_build_app(secret="secret"))
    body = b'{"user_id":"u1","text":"hi"}'
    res = client.post("/webhook", data=body, headers={"X-Webhook-Signature": _sig("secret", body)})
    assert res.status_code == 200


def test_tampered_body_with_old_signature_rejected() -> None:
    client = TestClient(_build_app(secret="secret"))
    original = b'{"user_id":"u1","text":"hi"}'
    tampered = b'{"user_id":"u1","text":"bye"}'
    res = client.post("/webhook", data=tampered, headers={"X-Webhook-Signature": _sig("secret", original)})
    assert res.status_code == 401


def test_signature_skipped_when_secret_missing() -> None:
    client = TestClient(_build_app(secret=None))
    res = client.post("/webhook", json={"user_id": "u1", "text": "hi"})
    assert res.status_code == 200


def test_rate_limit_exceeded_for_same_user() -> None:
    client = TestClient(_build_app(secret=None, rpm=10))
    for _ in range(10):
        ok = client.post("/webhook", json={"user_id": "u1", "text": "hi"})
        assert ok.status_code == 200
    blocked = client.post("/webhook", json={"user_id": "u1", "text": "hi"})
    assert blocked.status_code == 429


def test_rate_limits_are_independent_per_user() -> None:
    client = TestClient(_build_app(secret=None, rpm=1))
    assert client.post("/webhook", json={"user_id": "u1", "text": "hi"}).status_code == 200
    assert client.post("/webhook", json={"user_id": "u2", "text": "hi"}).status_code == 200
