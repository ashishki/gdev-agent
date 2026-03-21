"""Cost ledger integration tests."""

from __future__ import annotations

import asyncio
import os
import re
from datetime import date, datetime, timezone

from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import fakeredis
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import create_async_engine

from app.agent import AgentService
from app.approval_store import RedisApprovalStore
from app.config import Settings, get_settings
from app.cost_ledger import BudgetExhaustedError, CostLedger
from app.db import _set_tenant_ctx, make_session_factory
from app.exceptions import BudgetError
from app.llm_client import TriageResult
from app.schemas import ClassificationResult, ExtractedFields, WebhookRequest
from app.store import EventStore

UTC = timezone.utc

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


async def _seed_tenant(
    database_url: str, tenant_id: UUID, slug: str, daily_budget_usd: Decimal
) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO tenants (tenant_id, name, slug, daily_budget_usd)
                    VALUES (:tenant_id, :name, :slug, :daily_budget_usd)
                    """
                ),
                {
                    "tenant_id": str(tenant_id),
                    "name": f"Tenant {slug}",
                    "slug": slug,
                    "daily_budget_usd": daily_budget_usd,
                },
            )
    finally:
        await engine.dispose()


async def _seed_cost(
    database_url: str, tenant_id: UUID, day: date, cost_usd: Decimal
) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO cost_ledger (tenant_id, date, input_tokens, output_tokens, cost_usd, request_count)
                    VALUES (:tenant_id, :date, 0, 0, :cost_usd, 1)
                    ON CONFLICT (tenant_id, date)
                    DO UPDATE SET cost_usd = EXCLUDED.cost_usd
                    """
                ),
                {"tenant_id": str(tenant_id), "date": day, "cost_usd": cost_usd},
            )
    finally:
        await engine.dispose()


async def _enable_gdev_app_login(database_url: str, password: str) -> str:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(f"ALTER ROLE gdev_app LOGIN PASSWORD '{password}'"),
            )
            await conn.execute(text("GRANT USAGE ON SCHEMA public TO gdev_app"))
            await conn.execute(
                text(
                    "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO gdev_app"
                )
            )
    finally:
        await engine.dispose()
    return make_url(database_url).set(username="gdev_app", password=password).render_as_string(hide_password=False)


class _TrackingLLM:
    def __init__(self) -> None:
        self.calls = 0

    def run_agent(
        self, text: str, user_id: str | None = None, max_turns: int = 5
    ) -> TriageResult:
        self.calls += 1
        _ = (text, user_id, max_turns)
        return TriageResult(
            classification=ClassificationResult(
                category="other", urgency="low", confidence=0.99
            ),
            extracted=ExtractedFields(platform="unknown"),
            draft_text="ok",
            input_tokens=10,
            output_tokens=5,
        )


def test_budget_exhausted_returns_429_before_llm_call(migrated_postgres: str) -> None:
    tenant_id = uuid4()
    today = datetime.now(UTC).date()
    asyncio.run(
        _seed_tenant(migrated_postgres, tenant_id, "budget-a", Decimal("0.0100"))
    )
    asyncio.run(_seed_cost(migrated_postgres, tenant_id, today, Decimal("0.0100")))
    app_url = asyncio.run(_enable_gdev_app_login(migrated_postgres, "gdev-app-pass"))

    llm = _TrackingLLM()
    engine = create_async_engine(app_url, poolclass=NullPool)
    store = EventStore(
        sqlite_path=None, db_session_factory=make_session_factory(engine)
    )
    agent = AgentService(
        settings=Settings(approval_categories=[]),
        store=store,
        approval_store=RedisApprovalStore(fakeredis.FakeRedis(), ttl_seconds=3600),
        llm_client=llm,
    )

    try:
        with pytest.raises(BudgetError) as exc:
            agent.process_webhook(
                WebhookRequest(
                    tenant_id=str(tenant_id),
                    text="hello",
                    user_id="user-1",
                )
            )
    finally:
        asyncio.run(engine.dispose())

    assert exc.value.status_code == 429
    assert exc.value.detail == {"error": {"code": "budget_exhausted"}}
    assert llm.calls == 0


def test_record_uses_upsert_and_accumulates_daily_usage(migrated_postgres: str) -> None:
    tenant_id = uuid4()
    today = datetime.now(UTC).date()
    asyncio.run(
        _seed_tenant(migrated_postgres, tenant_id, "budget-b", Decimal("10.0000"))
    )
    app_url = asyncio.run(_enable_gdev_app_login(migrated_postgres, "gdev-app-pass"))

    engine = create_async_engine(app_url, poolclass=NullPool)
    session_factory = make_session_factory(engine)
    ledger = CostLedger()

    async def _record_twice() -> None:
        async with session_factory() as session:
            async with session.begin():
                await _set_tenant_ctx(session, str(tenant_id))
                await ledger.record(
                    tenant_id, today, 100, 20, Decimal("0.1000"), session
                )
                await ledger.record(
                    tenant_id, today, 100, 20, Decimal("0.1000"), session
                )

    async def _fetch_row() -> tuple[int, int, Decimal, int]:
        admin_engine = create_async_engine(migrated_postgres)
        try:
            async with admin_engine.connect() as conn:
                result = await conn.execute(
                    text(
                        """
                        SELECT input_tokens, output_tokens, cost_usd, request_count
                        FROM cost_ledger
                        WHERE tenant_id = :tenant_id AND date = :date
                        """
                    ),
                    {"tenant_id": str(tenant_id), "date": today},
                )
                row = result.mappings().one()
                return (
                    int(row["input_tokens"]),
                    int(row["output_tokens"]),
                    Decimal(str(row["cost_usd"])),
                    int(row["request_count"]),
                )
        finally:
            await admin_engine.dispose()

    try:
        asyncio.run(_record_twice())
    finally:
        asyncio.run(engine.dispose())

    input_tokens, output_tokens, cost_usd, request_count = asyncio.run(_fetch_row())
    assert input_tokens == 200
    assert output_tokens == 40
    assert cost_usd == Decimal("0.2000")
    assert request_count == 2


def test_check_budget_isolated_per_tenant(migrated_postgres: str) -> None:
    tenant_a = uuid4()
    tenant_b = uuid4()
    today = datetime.now(UTC).date()
    asyncio.run(
        _seed_tenant(migrated_postgres, tenant_a, "budget-c", Decimal("1.0000"))
    )
    asyncio.run(
        _seed_tenant(migrated_postgres, tenant_b, "budget-d", Decimal("1.0000"))
    )
    asyncio.run(_seed_cost(migrated_postgres, tenant_a, today, Decimal("1.0000")))
    app_url = asyncio.run(_enable_gdev_app_login(migrated_postgres, "gdev-app-pass"))

    engine = create_async_engine(app_url, poolclass=NullPool)
    session_factory = make_session_factory(engine)
    ledger = CostLedger()

    async def _check(tenant_id: UUID) -> None:
        async with session_factory() as session:
            async with session.begin():
                await _set_tenant_ctx(session, str(tenant_id))
                await ledger.check_budget(tenant_id, session)

    try:
        with pytest.raises(BudgetExhaustedError):
            asyncio.run(_check(tenant_a))
        asyncio.run(_check(tenant_b))
    finally:
        asyncio.run(engine.dispose())
