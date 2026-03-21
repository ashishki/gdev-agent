"""Integration coverage for persisted RCA cluster membership."""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.config import Settings, get_settings
from app.db import _set_tenant_ctx, make_session_factory
from app.jobs.rca_clusterer import RCAClusterer
from app.routers.clusters import get_cluster

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.integration


def _docker_available() -> bool:
    try:
        import docker  # type: ignore[import-untyped]

        docker.from_env(timeout=2)
        return True
    except Exception:
        return False


@pytest.fixture
def postgres_url() -> str:
    if _docker_available():
        pytest.importorskip("testcontainers.postgres")
        from testcontainers.postgres import PostgresContainer

        with PostgresContainer("pgvector/pgvector:pg16") as container:
            sync_url = container.get_connection_url()
            yield re.sub(r"^postgresql(\+\w+)?://", "postgresql+asyncpg://", sync_url)
        return

    test_url = os.environ.get("TEST_DATABASE_URL")
    if test_url:
        yield test_url
        return

    pytest.skip("No Docker and no TEST_DATABASE_URL configured")


@pytest.fixture
def migrated_postgres(postgres_url: str, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    get_settings.cache_clear()

    cfg = Config(str(ROOT / "alembic.ini"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")

    yield postgres_url

    command.downgrade(cfg, "base")
    get_settings.cache_clear()


async def _execute(database_url: str, statement: str, params: dict[str, object]) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(statement), params)
    finally:
        await engine.dispose()


async def _fetch_one(
    database_url: str, statement: str, params: dict[str, object]
) -> tuple[object, ...] | None:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text(statement), params)
            row = result.first()
            if row is None:
                return None
            return tuple(row)
    finally:
        await engine.dispose()


async def _enable_role_login(database_url: str, role: str, password: str) -> str:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(f"ALTER ROLE {role} LOGIN PASSWORD '{password}'"))
            await conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
            await conn.execute(
                text(
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}"
                )
            )
    finally:
        await engine.dispose()

    return make_url(database_url).set(username=role, password=password).render_as_string(
        hide_password=False
    )


class _LLMStub:
    async def summarize_cluster_async(self, texts: list[str]) -> dict[str, str]:
        return {
            "label": "Payments",
            "summary": f"{len(texts)} related tickets",
            "severity": "high",
        }


@pytest.mark.integration
def test_cluster_membership_persists_and_cluster_detail_reads_from_db(
    migrated_postgres: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    ticket_ids = [uuid4(), uuid4(), uuid4()]

    asyncio.run(
        _execute(
            migrated_postgres,
            """
            INSERT INTO tenants (tenant_id, name, slug)
            VALUES (:tenant_id, :name, :slug)
            """,
            {
                "tenant_id": str(tenant_id),
                "name": "Tenant clu",
                "slug": "tenant-clu",
            },
        )
    )
    for index, ticket_id in enumerate(ticket_ids, start=1):
        asyncio.run(
            _execute(
                migrated_postgres,
                """
                INSERT INTO tickets (ticket_id, tenant_id, message_id, user_id_hash, raw_text)
                VALUES (:ticket_id, :tenant_id, :message_id, :user_id_hash, :raw_text)
                """,
                {
                    "ticket_id": str(ticket_id),
                    "tenant_id": str(tenant_id),
                    "message_id": f"m-{index}",
                    "user_id_hash": "h",
                    "raw_text": f"payment failed {index}",
                },
            )
        )
        asyncio.run(
            _execute(
                migrated_postgres,
                """
                INSERT INTO ticket_embeddings (ticket_id, tenant_id, embedding, model_version)
                VALUES (:ticket_id, :tenant_id, :embedding, :model_version)
                """,
                {
                    "ticket_id": str(ticket_id),
                    "tenant_id": str(tenant_id),
                    "embedding": "[" + ",".join(["0.1"] * 1024) + "]",
                    "model_version": "test",
                },
            )
        )

    app_url = asyncio.run(
        _enable_role_login(migrated_postgres, "gdev_app", "gdev-app-pass")
    )
    admin_url = asyncio.run(
        _enable_role_login(migrated_postgres, "gdev_admin", "gdev-admin-pass")
    )

    app_engine = create_async_engine(app_url, poolclass=NullPool)
    admin_engine = create_async_engine(admin_url, poolclass=NullPool)
    app_session_factory = make_session_factory(app_engine)
    admin_session_factory = make_session_factory(admin_engine)

    clusterer = RCAClusterer(
        settings=Settings(
            anthropic_api_key="test-key",
            database_url=migrated_postgres,
        ),
        db_session_factory=app_session_factory,
        llm_client=_LLMStub(),
        admin_session_factory=admin_session_factory,
    )

    async def _run() -> None:
        monkeypatch.setattr(clusterer, "_dbscan", lambda embeddings, eps, min_samples: [0, 0, 0])
        await clusterer.run_tenant(str(tenant_id))

        async with app_session_factory() as session:
            async with session.begin():
                await _set_tenant_ctx(session, str(tenant_id))
                cluster_row = (
                    (
                        await session.execute(
                            text(
                                """
                                SELECT cluster_id
                                FROM cluster_summaries
                                WHERE tenant_id = :tenant_id
                                LIMIT 1
                                """
                            ),
                            {"tenant_id": str(tenant_id)},
                        )
                    )
                    .first()
                )
                assert cluster_row is not None
                cluster_id = cluster_row[0]

                member_count = (
                    (
                        await session.execute(
                            text(
                                """
                                SELECT COUNT(*)
                                FROM rca_cluster_members
                                WHERE cluster_id = :cluster_id
                                """
                            ),
                            {"cluster_id": str(cluster_id)},
                        )
                    )
                    .scalar_one()
                )
                assert int(member_count) == 3

                await session.execute(
                    text("DELETE FROM ticket_embeddings WHERE tenant_id = :tenant_id"),
                    {"tenant_id": str(tenant_id)},
                )

                response = await get_cluster(
                    cluster_id=UUID(str(cluster_id)),
                    request=SimpleNamespace(state=SimpleNamespace(tenant_id=tenant_id)),
                    db=session,
                )
                assert len(response.data[0].ticket_ids) == 3
                assert set(response.data[0].ticket_ids) == set(ticket_ids)

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(clusterer.aclose())
        asyncio.run(app_engine.dispose())
        asyncio.run(admin_engine.dispose())
