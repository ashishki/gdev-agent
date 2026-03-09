"""Database engine and session utilities."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings


def make_engine(settings: Settings) -> AsyncEngine:
    """Create the async SQLAlchemy engine."""
    database_url = settings.test_database_url or (
        str(settings.database_url) if settings.database_url is not None else None
    )
    if not database_url:
        raise ValueError("DATABASE_URL or TEST_DATABASE_URL is required")
    sqlite = database_url.startswith("sqlite")
    kwargs: dict[str, int | bool] = {"pool_pre_ping": not sqlite}
    if not sqlite:
        kwargs["pool_size"] = settings.db_pool_size
        kwargs["max_overflow"] = settings.db_max_overflow
    return create_async_engine(database_url, **kwargs)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create the async session factory for request-scoped sessions."""
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a session with tenant RLS context set for the transaction."""
    tenant_id = getattr(request.state, "tenant_id", None)
    async with request.app.state.db_session_factory() as session:
        async with session.begin():
            if tenant_id is not None:
                await session.execute(
                    text("SET LOCAL app.current_tenant_id = :tid"),
                    {"tid": str(tenant_id)},
                )
            yield session
