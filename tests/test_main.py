"""Startup lifespan tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI

from app import main
from app.config import Settings


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
    warning = _stub_runtime(monkeypatch, Settings(anthropic_api_key="k", webhook_secret=None))

    async def _run() -> None:
        async with main.lifespan(FastAPI()):
            pass

    asyncio.run(_run())
    assert warning.call_count == 1
    assert warning.call_args.kwargs["extra"]["event"] == "security_degraded"


def test_startup_no_warning_when_webhook_secret_present(monkeypatch) -> None:
    warning = _stub_runtime(monkeypatch, Settings(anthropic_api_key="k", webhook_secret="secret"))

    async def _run() -> None:
        async with main.lifespan(FastAPI()):
            pass

    asyncio.run(_run())
    assert warning.call_count == 0
