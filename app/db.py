"""Database engine and session utilities."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import UUID

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import Settings


async def _set_tenant_ctx(session: AsyncSession, tenant_id: str | None) -> None:
    """Set transaction-local tenant context when a tenant id is present."""
    if tenant_id is None:
        return
    tenant_uuid = UUID(str(tenant_id))
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_uuid)},
    )


def make_engine(settings: Settings) -> AsyncEngine:
    """Create the async SQLAlchemy engine."""
    database_url = settings.test_database_url or (
        str(settings.database_url) if settings.database_url is not None else None
    )
    if not database_url:
        raise ValueError("DATABASE_URL or TEST_DATABASE_URL is required")
    sqlite = database_url.startswith("sqlite")
    kwargs: dict[str, object] = {"pool_pre_ping": not sqlite}
    if not sqlite:
        kwargs["poolclass"] = NullPool
    return create_async_engine(database_url, **kwargs)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create the async session factory for request-scoped sessions."""
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a session with tenant RLS context set for the transaction."""
    tenant_id = getattr(request.state, "tenant_id", None)
    async with request.app.state.db_session_factory() as session:
        async with session.begin():
            await _set_tenant_ctx(session, tenant_id)
            yield session
