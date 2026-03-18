"""EventStore integration tests against Postgres."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.db import make_session_factory
from app.schemas import (
    AuditLogEntry,
    ClassificationResult,
    ExtractedFields,
    ProposedAction,
    WebhookRequest,
)
import app.store
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
                {"tenant_id": str(tenant_id), "name": "Tenant", "slug": slug},
            )
    finally:
        await engine.dispose()


async def _counts_for_tenant(database_url: str, tenant_id: UUID) -> dict[str, int]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            counts: dict[str, int] = {}
            for table_name in (
                "tickets",
                "ticket_classifications",
                "ticket_extracted_fields",
                "proposed_actions",
                "audit_log",
            ):
                result = await conn.execute(
                    text(
                        f"SELECT COUNT(*) FROM {table_name} WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": str(tenant_id)},
                )
                counts[table_name] = int(result.scalar_one())
            return counts
    finally:
        await engine.dispose()


async def _ticket_user_hash(database_url: str, tenant_id: UUID) -> str | None:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT user_id_hash
                    FROM tickets
                    WHERE tenant_id = :tenant_id
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"tenant_id": str(tenant_id)},
            )
            return result.scalar_one_or_none()
    finally:
        await engine.dispose()


async def _drop_audit_log(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE audit_log"))
    finally:
        await engine.dispose()


async def _enable_gdev_app_login(database_url: str, password: str) -> str:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("ALTER ROLE gdev_app LOGIN PASSWORD :password"),
                {"password": password},
            )
            await conn.execute(text("GRANT USAGE ON SCHEMA public TO gdev_app"))
            await conn.execute(
                text(
                    "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO gdev_app"
                )
            )
    finally:
        await engine.dispose()

    return str(make_url(database_url).set(username="gdev_app", password=password))


def _build_event_inputs(
    tenant_id: UUID,
) -> tuple[
    WebhookRequest, ClassificationResult, ExtractedFields, ProposedAction, AuditLogEntry
]:
    payload = WebhookRequest(
        tenant_id=str(tenant_id),
        request_id="req-1",
        message_id="msg-1",
        user_id="user-42",
        text="Payment failed after purchase",
        metadata={"chat_id": "chat-1"},
    )
    classification = ClassificationResult(
        category="billing", urgency="high", confidence=0.93
    )
    extracted = ExtractedFields(platform="telegram", transaction_id="tx-1")
    action = ProposedAction(
        tool="create_ticket_and_reply",
        payload={"title": "[billing] support request", "tenant_id": str(tenant_id)},
        risky=True,
    )
    audit_entry = AuditLogEntry(
        timestamp="2026-03-04T10:00:00Z",
        request_id="req-1",
        tenant_id=str(tenant_id),
        message_id="msg-1",
        user_id=hashlib.sha256("user-42".encode()).hexdigest(),
        category="billing",
        urgency="high",
        confidence=0.93,
        action="create_ticket_and_reply",
        status="pending",
        latency_ms=120,
        cost_usd=0.001,
    )
    return payload, classification, extracted, action, audit_entry


def _make_store(database_url: str) -> tuple[EventStore, object]:
    engine = create_async_engine(database_url)
    session_factory = make_session_factory(engine)
    return EventStore(sqlite_path=None, db_session_factory=session_factory), engine


def test_persist_pipeline_run_uses_shared_run_blocking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    store = EventStore(sqlite_path=None, db_session_factory=lambda: None)
    payload, classification, extracted, action, audit_entry = _build_event_inputs(
        tenant_id
    )
    called = {"value": False}

    def fake_run_blocking(coroutine):
        called["value"] = True
        coroutine.close()
        return "ticket-id"

    monkeypatch.setattr(app.store, "run_blocking", fake_run_blocking)

    assert (
        store.persist_pipeline_run(
            payload,
            classification,
            extracted,
            action,
            audit_entry,
        )
        == "ticket-id"
    )
    assert called["value"] is True


def test_persist_pipeline_run_writes_all_rows_and_hashes_user_id(
    migrated_postgres: str,
) -> None:
    tenant_id = uuid4()
    asyncio.run(_seed_tenant(migrated_postgres, tenant_id, "tenant-a"))

    store, engine = _make_store(migrated_postgres)
    payload, classification, extracted, action, audit_entry = _build_event_inputs(
        tenant_id
    )

    try:
        store.persist_pipeline_run(
            payload,
            classification,
            extracted,
            action,
            audit_entry,
            input_tokens=100,
            output_tokens=20,
        )
    finally:
        asyncio.run(engine.dispose())

    counts = asyncio.run(_counts_for_tenant(migrated_postgres, tenant_id))
    assert counts == {
        "tickets": 1,
        "ticket_classifications": 1,
        "ticket_extracted_fields": 1,
        "proposed_actions": 1,
        "audit_log": 1,
    }

    expected_hash = hashlib.sha256("user-42".encode()).hexdigest()
    assert asyncio.run(_ticket_user_hash(migrated_postgres, tenant_id)) == expected_hash


def test_persist_pipeline_run_rolls_back_on_write_failure(
    migrated_postgres: str,
) -> None:
    tenant_id = uuid4()
    asyncio.run(_seed_tenant(migrated_postgres, tenant_id, "tenant-b"))
    asyncio.run(_drop_audit_log(migrated_postgres))

    store, engine = _make_store(migrated_postgres)
    payload = WebhookRequest(
        tenant_id=str(tenant_id),
        message_id="msg-2",
        user_id="user-99",
        text="Bug report",
    )
    classification = ClassificationResult(
        category="bug_report", urgency="low", confidence=0.91
    )
    extracted = ExtractedFields(platform="discord")
    action = ProposedAction(
        tool="create_ticket_and_reply", payload={"tenant_id": str(tenant_id)}
    )
    audit_entry = AuditLogEntry(
        timestamp="2026-03-04T10:00:00Z",
        request_id="req-2",
        tenant_id=str(tenant_id),
        message_id="msg-2",
        category="bug_report",
        urgency="low",
        confidence=0.91,
        action="create_ticket_and_reply",
        status="executed",
        latency_ms=90,
        cost_usd=0.001,
    )

    try:
        with pytest.raises(Exception):
            store.persist_pipeline_run(
                payload, classification, extracted, action, audit_entry
            )
    finally:
        asyncio.run(engine.dispose())

    engine_verify = create_async_engine(migrated_postgres)
    try:

        async def _verify_no_partial_rows() -> dict[str, int]:
            async with engine_verify.connect() as conn:
                counts: dict[str, int] = {}
                for table_name in (
                    "tickets",
                    "ticket_classifications",
                    "ticket_extracted_fields",
                    "proposed_actions",
                ):
                    result = await conn.execute(
                        text(
                            f"SELECT COUNT(*) FROM {table_name} WHERE tenant_id = :tenant_id"
                        ),
                        {"tenant_id": str(tenant_id)},
                    )
                    counts[table_name] = int(result.scalar_one())
                return counts

        counts = asyncio.run(_verify_no_partial_rows())
    finally:
        asyncio.run(engine_verify.dispose())

    assert counts == {
        "tickets": 0,
        "ticket_classifications": 0,
        "ticket_extracted_fields": 0,
        "proposed_actions": 0,
    }


def test_persist_pipeline_run_succeeds_as_gdev_app_with_rls(
    migrated_postgres: str,
) -> None:
    tenant_id = uuid4()
    asyncio.run(_seed_tenant(migrated_postgres, tenant_id, "tenant-c"))
    app_url = asyncio.run(_enable_gdev_app_login(migrated_postgres, "gdev-app-pass"))

    store, engine = _make_store(app_url)
    payload, classification, extracted, action, audit_entry = _build_event_inputs(
        tenant_id
    )
    try:
        store.persist_pipeline_run(
            payload,
            classification,
            extracted,
            action,
            audit_entry,
            input_tokens=50,
            output_tokens=10,
        )
    finally:
        asyncio.run(engine.dispose())

    counts = asyncio.run(_counts_for_tenant(migrated_postgres, tenant_id))
    assert counts == {
        "tickets": 1,
        "ticket_classifications": 1,
        "ticket_extracted_fields": 1,
        "proposed_actions": 1,
        "audit_log": 1,
    }


def test_cross_tenant_insert_blocked_by_rls_for_gdev_app(
    migrated_postgres: str,
) -> None:
    tenant_a = uuid4()
    tenant_b = uuid4()
    asyncio.run(_seed_tenant(migrated_postgres, tenant_a, "tenant-d"))
    asyncio.run(_seed_tenant(migrated_postgres, tenant_b, "tenant-e"))
    app_url = asyncio.run(_enable_gdev_app_login(migrated_postgres, "gdev-app-pass"))

    engine = create_async_engine(app_url)
    session_factory = make_session_factory(engine)

    async def _cross_tenant_insert() -> None:
        async with session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("SET LOCAL app.current_tenant_id = :tid"),
                    {"tid": str(tenant_a)},
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
                        "message_id": "cross-tenant",
                        "user_id_hash": hashlib.sha256("u".encode()).hexdigest(),
                        "raw_text": "x",
                    },
                )

    try:
        with pytest.raises(Exception):
            asyncio.run(_cross_tenant_insert())
    finally:
        asyncio.run(engine.dispose())
