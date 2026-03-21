"""Database engine and session dependency tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")

from app import db
from app.config import Settings


class _SessionContext:
    def __init__(self) -> None:
        self.execute = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def begin(self):
        return _BeginContext()


class _BeginContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _SessionFactory:
    def __init__(self, session: _SessionContext) -> None:
        self._session = session

    def __call__(self) -> _SessionContext:
        return self._session


def test_make_engine_uses_test_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(test_database_url="sqlite+aiosqlite:///:memory:")
    calls: dict[str, object] = {}

    def _fake_create_async_engine(url: str, **kwargs):
        calls["url"] = url
        calls["kwargs"] = kwargs
        return "engine"

    monkeypatch.setattr(db, "create_async_engine", _fake_create_async_engine)

    engine = db.make_engine(settings)

    assert engine == "engine"
    assert calls["url"] == "sqlite+aiosqlite:///:memory:"
    assert calls["kwargs"] == {"pool_pre_ping": False}


def test_make_engine_sqlite_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(test_database_url="sqlite+aiosqlite:///:memory:")
    calls: dict[str, object] = {}

    def _fake_create_async_engine(url: str, **kwargs):
        calls["url"] = url
        calls["kwargs"] = kwargs
        return "engine"

    monkeypatch.setattr(db, "create_async_engine", _fake_create_async_engine)

    engine = db.make_engine(settings)

    assert engine == "engine"
    assert calls["url"] == "sqlite+aiosqlite:///:memory:"
    assert "pool_size" not in calls["kwargs"]
    assert "max_overflow" not in calls["kwargs"]
    assert calls["kwargs"]["pool_pre_ping"] is False


def test_get_db_session_sets_local_tenant_id() -> None:
    session = _SessionContext()
    tenant_id = str(uuid4())
    request = SimpleNamespace(
        state=SimpleNamespace(tenant_id=tenant_id),
        app=SimpleNamespace(state=SimpleNamespace(db_session_factory=_SessionFactory(session))),
    )

    async def _run() -> _SessionContext:
        session_gen = db.get_db_session(request)
        yielded = await anext(session_gen)
        await session_gen.aclose()
        return yielded

    yielded_session = asyncio.run(_run())

    assert yielded_session is session
    session.execute.assert_awaited_once()
    statement, params = session.execute.await_args.args
    assert str(statement) == f"SET LOCAL app.current_tenant_id = '{tenant_id}'"
    assert params == {}


def test_get_db_session_skips_set_local_without_tenant_id() -> None:
    session = _SessionContext()
    request = SimpleNamespace(
        state=SimpleNamespace(tenant_id=None),
        app=SimpleNamespace(state=SimpleNamespace(db_session_factory=_SessionFactory(session))),
    )

    async def _run() -> None:
        session_gen = db.get_db_session(request)
        await anext(session_gen)
        await session_gen.aclose()

    asyncio.run(_run())

    session.execute.assert_not_awaited()


def test_set_tenant_ctx_rejects_invalid_tenant_id() -> None:
    session = _SessionContext()

    async def _run() -> None:
        await db._set_tenant_ctx(session, "not-a-uuid")

    with pytest.raises(ValueError):
        asyncio.run(_run())
    session.execute.assert_not_awaited()
