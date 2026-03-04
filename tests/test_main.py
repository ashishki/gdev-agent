"""Startup lifespan tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi import HTTPException

from app import main
from app.config import Settings
from app.schemas import ApproveRequest, WebhookRequest


def _stub_runtime(monkeypatch, settings: Settings) -> Mock:
    warning = Mock()
    engine = SimpleNamespace(dispose=AsyncMock())
    async_redis = SimpleNamespace(aclose=AsyncMock())
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "configure_logging", lambda *_: None)
    monkeypatch.setattr(main.LOGGER, "warning", warning)
    monkeypatch.setattr(main.redis, "from_url", lambda *_: SimpleNamespace(ping=lambda: None))
    monkeypatch.setattr(main.aioredis, "from_url", lambda *_: async_redis)
    monkeypatch.setattr(main, "make_engine", lambda *_: engine)
    monkeypatch.setattr(main, "make_session_factory", lambda *_: object())
    monkeypatch.setattr(main, "WebhookSecretStore", lambda *_, **__: object())
    monkeypatch.setattr(main, "EventStore", lambda **_: object())
    monkeypatch.setattr(main, "RedisApprovalStore", lambda *_, **__: object())
    monkeypatch.setattr(main, "DedupCache", lambda *_, **__: object())
    monkeypatch.setattr(main, "TenantRegistry", lambda *_, **__: object())
    monkeypatch.setattr(main, "SheetsClient", lambda *_, **__: object())
    monkeypatch.setattr(main, "TelegramClient", lambda *_, **__: object())
    monkeypatch.setattr(main, "AgentService", lambda **_: object())
    return warning


def test_startup_no_warning_when_webhook_secret_missing(monkeypatch) -> None:
    warning = _stub_runtime(
        monkeypatch,
        Settings(anthropic_api_key="k", webhook_secret=None, approve_secret="approve-secret"),
    )

    async def _run() -> None:
        async with main.lifespan(FastAPI()):
            pass

    asyncio.run(_run())
    assert warning.call_count == 0


def test_startup_warns_when_webhook_secret_present(monkeypatch) -> None:
    warning = _stub_runtime(
        monkeypatch,
        Settings(anthropic_api_key="k", webhook_secret="secret", approve_secret="approve-secret"),
    )

    async def _run() -> None:
        async with main.lifespan(FastAPI()):
            pass

    asyncio.run(_run())
    assert warning.call_count == 1
    assert warning.call_args.kwargs["extra"]["event"] == "security_degraded"


def test_startup_warns_when_approve_secret_missing(monkeypatch) -> None:
    warning = _stub_runtime(
        monkeypatch,
        Settings(anthropic_api_key="k", webhook_secret="secret", approve_secret=None),
    )

    async def _run() -> None:
        async with main.lifespan(FastAPI()):
            pass

    asyncio.run(_run())
    assert warning.call_count == 2
    assert warning.call_args.kwargs["extra"]["event"] == "security_degraded"


def test_approve_rejects_when_secret_missing_or_wrong() -> None:
    main.app.state.settings = Settings(anthropic_api_key="k", approve_secret="secret")
    main.app.state.agent = SimpleNamespace(
        approve=lambda payload, jwt_tenant_id=None: {"unexpected": payload.pending_id, "tenant": jwt_tenant_id}
    )
    payload = ApproveRequest(pending_id="p1", approved=True)

    try:
        main.approve(payload, request=SimpleNamespace(headers={}))
        assert False, "Expected HTTPException for missing X-Approve-Secret"
    except HTTPException as exc:
        assert exc.status_code == 401
        assert exc.detail == "Unauthorized"

    try:
        main.approve(payload, request=SimpleNamespace(headers={"X-Approve-Secret": "wrong"}))
        assert False, "Expected HTTPException for invalid X-Approve-Secret"
    except HTTPException as exc:
        assert exc.status_code == 401
        assert exc.detail == "Unauthorized"


def test_approve_allows_when_secret_matches() -> None:
    approved = {"status": "approved", "pending_id": "p1", "result": {"ok": True}}
    main.app.state.settings = Settings(anthropic_api_key="k", approve_secret="secret")
    main.app.state.agent = SimpleNamespace(approve=lambda payload, jwt_tenant_id=None: approved)

    response = main.approve(
        ApproveRequest(pending_id="p1", approved=True),
        request=SimpleNamespace(
            headers={"X-Approve-Secret": "secret"},
            state=SimpleNamespace(tenant_id="tenant-a"),
        ),
    )

    assert response == approved


def test_lifespan_creates_and_closes_db_engine(monkeypatch) -> None:
    settings = Settings(anthropic_api_key="k", approve_secret="approve-secret")
    engine = SimpleNamespace(dispose=AsyncMock())
    warning = _stub_runtime(monkeypatch, settings)
    monkeypatch.setattr(main, "make_engine", lambda *_: engine)

    async def _run() -> None:
        app = FastAPI()
        async with main.lifespan(app):
            assert app.state.db_engine is engine

    asyncio.run(_run())

    assert warning.call_count == 0
    engine.dispose.assert_awaited_once()


def test_webhook_rejects_missing_tenant_id() -> None:
    main.app.state.dedup = SimpleNamespace(check=lambda *_: None, set=lambda *_: None)
    main.app.state.agent = SimpleNamespace(process_webhook=lambda *_args, **_kwargs: None)

    with pytest.raises(HTTPException) as exc:
        main.webhook(
            WebhookRequest(text="hello"),
            request=SimpleNamespace(state=SimpleNamespace()),
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "tenant_id is required"


def test_webhook_rejects_non_uuid_tenant_id() -> None:
    main.app.state.dedup = SimpleNamespace(check=lambda *_: None, set=lambda *_: None)
    main.app.state.agent = SimpleNamespace(process_webhook=lambda *_args, **_kwargs: None)

    with pytest.raises(HTTPException) as exc:
        main.webhook(
            WebhookRequest(text="hello", tenant_id="not-a-uuid"),
            request=SimpleNamespace(state=SimpleNamespace()),
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "tenant_id must be a valid UUID"


def test_webhook_propagates_budget_exhausted_http_429() -> None:
    def _raise_budget(*_args, **_kwargs):
        raise HTTPException(status_code=429, detail={"error": {"code": "budget_exhausted"}})

    main.app.state.dedup = SimpleNamespace(check=lambda *_: None, set=lambda *_: None)
    main.app.state.agent = SimpleNamespace(process_webhook=_raise_budget)

    with pytest.raises(HTTPException) as exc:
        main.webhook(
            WebhookRequest(text="hello", tenant_id="3d0f5f00-ec44-4d3f-893f-c8f89ee5f80c"),
            request=SimpleNamespace(state=SimpleNamespace()),
        )

    assert exc.value.status_code == 429
    assert exc.value.detail == {"error": {"code": "budget_exhausted"}}
