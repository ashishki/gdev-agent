"""Startup lifespan tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi import HTTPException

from app import main
from app.config import Settings
from app.schemas import ApproveRequest


def _stub_runtime(monkeypatch, settings: Settings) -> Mock:
    warning = Mock()
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "configure_logging", lambda *_: None)
    monkeypatch.setattr(main.LOGGER, "warning", warning)
    monkeypatch.setattr(main.redis, "from_url", lambda *_: SimpleNamespace(ping=lambda: None))
    monkeypatch.setattr(main, "EventStore", lambda **_: object())
    monkeypatch.setattr(main, "RedisApprovalStore", lambda *_, **__: object())
    monkeypatch.setattr(main, "DedupCache", lambda *_, **__: object())
    monkeypatch.setattr(main, "SheetsClient", lambda *_, **__: object())
    monkeypatch.setattr(main, "TelegramClient", lambda *_, **__: object())
    monkeypatch.setattr(main, "AgentService", lambda **_: object())
    return warning


def test_startup_warns_when_webhook_secret_missing(monkeypatch) -> None:
    warning = _stub_runtime(
        monkeypatch,
        Settings(anthropic_api_key="k", webhook_secret=None, approve_secret="approve-secret"),
    )

    async def _run() -> None:
        async with main.lifespan(FastAPI()):
            pass

    asyncio.run(_run())
    assert warning.call_count == 1
    assert warning.call_args.kwargs["extra"]["event"] == "security_degraded"


def test_startup_no_warning_when_webhook_secret_present(monkeypatch) -> None:
    warning = _stub_runtime(
        monkeypatch,
        Settings(anthropic_api_key="k", webhook_secret="secret", approve_secret="approve-secret"),
    )

    async def _run() -> None:
        async with main.lifespan(FastAPI()):
            pass

    asyncio.run(_run())
    assert warning.call_count == 0


def test_startup_warns_when_approve_secret_missing(monkeypatch) -> None:
    warning = _stub_runtime(
        monkeypatch,
        Settings(anthropic_api_key="k", webhook_secret="secret", approve_secret=None),
    )

    async def _run() -> None:
        async with main.lifespan(FastAPI()):
            pass

    asyncio.run(_run())
    assert warning.call_count == 1
    assert warning.call_args.kwargs["extra"]["event"] == "security_degraded"


def test_approve_rejects_when_secret_missing_or_wrong() -> None:
    main.app.state.settings = Settings(anthropic_api_key="k", approve_secret="secret")
    main.app.state.agent = SimpleNamespace(approve=lambda payload: {"unexpected": payload.pending_id})
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
    main.app.state.agent = SimpleNamespace(approve=lambda payload: approved)

    response = main.approve(
        ApproveRequest(pending_id="p1", approved=True),
        request=SimpleNamespace(headers={"X-Approve-Secret": "secret"}),
    )

    assert response == approved
