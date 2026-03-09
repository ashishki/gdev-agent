"""Cross-tenant isolation integration tests."""

from __future__ import annotations

import asyncio
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import fakeredis
import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.agent import AgentService
from app.approval_store import RedisApprovalStore
from app.config import Settings, get_settings
from app.db import make_session_factory
from app.schemas import (
    ApproveRequest,
    AuditLogEntry,
    ClassificationResult,
    ExtractedFields,
    PendingDecision,
    ProposedAction,
    WebhookRequest,
)
from app.store import EventStore

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


async def _seed_tenant(database_url: str, tenant_id: UUID, slug: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO tenants (tenant_id, name, slug) VALUES (:tenant_id, :name, :slug)"
                ),
                {"tenant_id": str(tenant_id), "name": f"Tenant {slug}", "slug": slug},
            )
    finally:
        await engine.dispose()


async def _seed_ticket(database_url: str, tenant_id: UUID, message_id: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO tickets (tenant_id, message_id, user_id_hash, raw_text)
                    VALUES (:tenant_id, :message_id, :user_id_hash, :raw_text)
                    """
                ),
                {
                    "tenant_id": str(tenant_id),
                    "message_id": message_id,
                    "user_id_hash": "h",
                    "raw_text": "seed",
                },
            )
    finally:
        await engine.dispose()


async def _enable_role_login(database_url: str, role: str, password: str) -> str:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(f"ALTER ROLE {role} LOGIN PASSWORD :password"),
                {"password": password},
            )
            await conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))
            await conn.execute(
                text(
                    f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}"
                )
            )
    finally:
        await engine.dispose()

    return str(make_url(database_url).set(username=role, password=password))


async def _count_rows_for_tenant(
    database_url: str, table_name: str, tenant_id: UUID
) -> int:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(f"SELECT COUNT(*) FROM {table_name} WHERE tenant_id = :tenant_id"),
                {"tenant_id": str(tenant_id)},
            )
            return int(result.scalar_one())
    finally:
        await engine.dispose()


def _event_store_payloads(
    tenant_id: UUID,
) -> tuple[
    WebhookRequest, ClassificationResult, ExtractedFields, ProposedAction, AuditLogEntry
]:
    payload = WebhookRequest(
        tenant_id=str(tenant_id),
        request_id="iso-req-1",
        message_id="iso-msg-1",
        user_id="iso-user",
        text="Billing charge issue",
    )
    classification = ClassificationResult(
        category="billing", urgency="high", confidence=0.92
    )
    extracted = ExtractedFields(platform="telegram", transaction_id="tx-iso")
    action = ProposedAction(
        tool="create_ticket_and_reply",
        payload={"tenant_id": str(tenant_id), "title": "Billing issue"},
        risky=True,
    )
    audit_entry = AuditLogEntry(
        timestamp="2026-03-04T10:00:00Z",
        request_id="iso-req-1",
        tenant_id=str(tenant_id),
        message_id="iso-msg-1",
        user_id="hash",
        category="billing",
        urgency="high",
        confidence=0.92,
        action="create_ticket_and_reply",
        status="pending",
        latency_ms=100,
        cost_usd=0.001,
    )
    return payload, classification, extracted, action, audit_entry


@pytest.mark.integration
def test_db_rls_read_isolation_for_gdev_app(migrated_postgres: str) -> None:
    tenant_a = uuid4()
    tenant_b = uuid4()
    asyncio.run(_seed_tenant(migrated_postgres, tenant_a, "iso-a"))
    asyncio.run(_seed_tenant(migrated_postgres, tenant_b, "iso-b"))
    asyncio.run(_seed_ticket(migrated_postgres, tenant_a, "a-msg"))
    asyncio.run(_seed_ticket(migrated_postgres, tenant_b, "b-msg"))
    app_url = asyncio.run(
        _enable_role_login(migrated_postgres, "gdev_app", "gdev-app-pass")
    )

    engine = create_async_engine(app_url)
    session_factory = make_session_factory(engine)

    async def _query_cross_tenant_rows() -> int:
        async with session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("SET LOCAL app.current_tenant_id = :tenant_id"),
                    {"tenant_id": str(tenant_a)},
                )
                result = await session.execute(
                    text("SELECT COUNT(*) FROM tickets WHERE tenant_id = :tenant_id"),
                    {"tenant_id": str(tenant_b)},
                )
                return int(result.scalar_one())

    try:
        cross_tenant_rows = asyncio.run(_query_cross_tenant_rows())
    finally:
        asyncio.run(engine.dispose())

    assert cross_tenant_rows == 0


@pytest.mark.integration
def test_db_rls_write_isolation_for_gdev_app(migrated_postgres: str) -> None:
    tenant_a = uuid4()
    tenant_b = uuid4()
    asyncio.run(_seed_tenant(migrated_postgres, tenant_a, "iso-c"))
    asyncio.run(_seed_tenant(migrated_postgres, tenant_b, "iso-d"))
    app_url = asyncio.run(
        _enable_role_login(migrated_postgres, "gdev_app", "gdev-app-pass")
    )

    engine = create_async_engine(app_url)
    session_factory = make_session_factory(engine)

    async def _attempt_cross_tenant_insert() -> None:
        async with session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("SET LOCAL app.current_tenant_id = :tenant_id"),
                    {"tenant_id": str(tenant_a)},
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO tickets (tenant_id, message_id, user_id_hash, raw_text)
                        VALUES (:tenant_id, :message_id, :user_id_hash, :raw_text)
                        """
                    ),
                    {
                        "tenant_id": str(tenant_b),
                        "message_id": "cross-tenant-write",
                        "user_id_hash": "h",
                        "raw_text": "should fail",
                    },
                )

    try:
        with pytest.raises(Exception):
            asyncio.run(_attempt_cross_tenant_insert())
    finally:
        asyncio.run(engine.dispose())


@pytest.mark.integration
def test_event_store_binds_all_rows_to_payload_tenant(migrated_postgres: str) -> None:
    tenant_a = uuid4()
    tenant_b = uuid4()
    asyncio.run(_seed_tenant(migrated_postgres, tenant_a, "iso-e"))
    asyncio.run(_seed_tenant(migrated_postgres, tenant_b, "iso-f"))
    app_url = asyncio.run(
        _enable_role_login(migrated_postgres, "gdev_app", "gdev-app-pass")
    )

    engine = create_async_engine(app_url)
    store = EventStore(
        sqlite_path=None, db_session_factory=make_session_factory(engine)
    )
    payload, classification, extracted, action, audit_entry = _event_store_payloads(
        tenant_a
    )
    try:
        store.persist_pipeline_run(
            payload,
            classification,
            extracted,
            action,
            audit_entry,
            input_tokens=10,
            output_tokens=2,
        )
    finally:
        asyncio.run(engine.dispose())

    for table_name in (
        "tickets",
        "ticket_classifications",
        "ticket_extracted_fields",
        "proposed_actions",
        "audit_log",
    ):
        assert (
            asyncio.run(_count_rows_for_tenant(migrated_postgres, table_name, tenant_a))
            == 1
        )
        assert (
            asyncio.run(_count_rows_for_tenant(migrated_postgres, table_name, tenant_b))
            == 0
        )


@pytest.mark.integration
def test_approve_cross_tenant_is_forbidden_and_pending_remains(
    migrated_postgres: str,
) -> None:
    tenant_a = uuid4()
    tenant_b = uuid4()
    asyncio.run(_seed_tenant(migrated_postgres, tenant_a, "iso-g"))
    asyncio.run(_seed_tenant(migrated_postgres, tenant_b, "iso-h"))
    app_url = asyncio.run(
        _enable_role_login(migrated_postgres, "gdev_app", "gdev-app-pass")
    )

    settings = Settings(approval_categories=["billing"], approval_ttl_seconds=3600)
    approval_store = RedisApprovalStore(fakeredis.FakeRedis(), ttl_seconds=3600)
    engine = create_async_engine(app_url)
    agent = AgentService(
        settings=settings,
        store=EventStore(
            sqlite_path=None, db_session_factory=make_session_factory(engine)
        ),
        approval_store=approval_store,
    )

    pending = PendingDecision(
        pending_id="isolation-pending-1",
        tenant_id=str(tenant_a),
        reason="manual approval required",
        user_id="user-1",
        expires_at=datetime.now(UTC) + timedelta(seconds=600),
        action=ProposedAction(
            tool="create_ticket_and_reply", payload={"x": 1}, risky=True
        ),
        draft_response="pending response",
    )
    approval_store.put_pending(pending)

    try:
        with pytest.raises(HTTPException) as exc:
            agent.approve(
                ApproveRequest(
                    pending_id=pending.pending_id, approved=True, reviewer="reviewer-1"
                ),
                jwt_tenant_id=str(tenant_b),
            )
    finally:
        asyncio.run(engine.dispose())

    assert exc.value.status_code == 403
    assert approval_store.get_pending(pending.pending_id) is not None


@pytest.mark.integration
def test_gdev_admin_has_bypassrls_and_sees_both_tenants(migrated_postgres: str) -> None:
    tenant_a = uuid4()
    tenant_b = uuid4()
    asyncio.run(_seed_tenant(migrated_postgres, tenant_a, "iso-i"))
    asyncio.run(_seed_tenant(migrated_postgres, tenant_b, "iso-j"))
    asyncio.run(_seed_ticket(migrated_postgres, tenant_a, "admin-a"))
    asyncio.run(_seed_ticket(migrated_postgres, tenant_b, "admin-b"))
    admin_url = asyncio.run(
        _enable_role_login(migrated_postgres, "gdev_admin", "gdev-admin-pass")
    )

    engine = create_async_engine(admin_url)

    async def _query_admin_visibility() -> tuple[int, int, bool]:
        async with engine.connect() as conn:
            count_a = await conn.execute(
                text("SELECT COUNT(*) FROM tickets WHERE tenant_id = :tenant_id"),
                {"tenant_id": str(tenant_a)},
            )
            count_b = await conn.execute(
                text("SELECT COUNT(*) FROM tickets WHERE tenant_id = :tenant_id"),
                {"tenant_id": str(tenant_b)},
            )
            role_result = await conn.execute(
                text("SELECT rolbypassrls FROM pg_roles WHERE rolname = 'gdev_admin'")
            )
            return (
                int(count_a.scalar_one()),
                int(count_b.scalar_one()),
                bool(role_result.scalar_one()),
            )

    try:
        tenant_a_count, tenant_b_count, rolbypassrls = asyncio.run(
            _query_admin_visibility()
        )
    finally:
        asyncio.run(engine.dispose())

    assert tenant_a_count == 1
    assert tenant_b_count == 1
    assert rolbypassrls is True
