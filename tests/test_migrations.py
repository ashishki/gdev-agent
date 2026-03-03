"""Migration tests for initial schema.

Runs upgrade + downgrade against either:
  - a Docker-launched pgvector/pgvector:pg16 container (preferred), OR
  - a local PostgreSQL instance when Docker is unavailable.

To use a local database set:
    TEST_DATABASE_URL=postgresql+asyncpg://user:pass@localhost/gdev_test pytest
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from app.config import get_settings

EXPECTED_TABLES = {
    "tenants",
    "tenant_users",
    "api_keys",
    "webhook_secrets",
    "tickets",
    "ticket_classifications",
    "ticket_extracted_fields",
    "proposed_actions",
    "pending_decisions",
    "approval_events",
    "audit_log",
    "ticket_embeddings",
    "cluster_summaries",
    "agent_configs",
    "cost_ledger",
    "eval_runs",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _root_dir() -> Path:
    return Path(__file__).resolve().parents[1]


async def _public_tables(database_url: str) -> set[str]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            return {row[0] for row in result}
    finally:
        await engine.dispose()


def _docker_available() -> bool:
    """Return True if Docker daemon is reachable."""
    try:
        import docker  # type: ignore[import-untyped]
        docker.from_env(timeout=2)
        return True
    except Exception:
        return False


def _run_migration_test(async_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Core logic: upgrade → assert tables → downgrade → assert empty."""
    from alembic import command
    from alembic.config import Config

    monkeypatch.setenv("DATABASE_URL", async_url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    get_settings.cache_clear()

    cfg = Config(str(_root_dir() / "alembic.ini"))

    # Ensure a clean slate for the downgrade assertion
    command.downgrade(cfg, "base")

    command.upgrade(cfg, "head")
    upgraded = asyncio.run(_public_tables(async_url))
    assert EXPECTED_TABLES.issubset(upgraded), f"Missing tables: {EXPECTED_TABLES - upgraded}"

    command.downgrade(cfg, "base")
    downgraded = asyncio.run(_public_tables(async_url))
    assert EXPECTED_TABLES.isdisjoint(downgraded), f"Tables not dropped: {EXPECTED_TABLES & downgraded}"

    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_initial_migration_upgrade_and_downgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("alembic")
    pytest.importorskip("sqlalchemy")

    # --- Path 1: Docker available → use pgvector container ---
    if _docker_available():
        pytest.importorskip("testcontainers.postgres")
        from testcontainers.postgres import PostgresContainer

        with PostgresContainer("pgvector/pgvector:pg16") as container:
            sync_url = container.get_connection_url()
            import re
            async_url = re.sub(r"^postgresql(\+\w+)?://", "postgresql+asyncpg://", sync_url)
            _run_migration_test(async_url, monkeypatch)
        return

    # --- Path 2: Explicit TEST_DATABASE_URL env var ---
    test_url = os.environ.get("TEST_DATABASE_URL")
    if test_url:
        _run_migration_test(test_url, monkeypatch)
        return

    # --- Path 3: Local Postgres via Unix socket, create gdev_test DB ---
    # asyncpg Unix socket URL: postgresql+asyncpg:///dbname (empty host = socket)
    # Pydantic PostgresDsn requires a non-empty host, so we pass it as
    # TEST_DATABASE_URL and bypass validation for the migration test only.
    try:
        import psycopg2  # type: ignore[import-untyped]
        conn = psycopg2.connect("dbname=postgres user=postgres host=/var/run/postgresql")
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("DROP DATABASE IF EXISTS gdev_test")
        cur.execute("CREATE DATABASE gdev_test")
        cur.execute("SELECT pg_postmaster_pid()")  # confirm connection is live
        cur.close()
        conn.close()
    except Exception as exc:
        pytest.skip(f"No Docker and no accessible local Postgres: {exc}")
        return

    # Use TCP localhost so the URL passes Pydantic's host-required validation.
    local_url = "postgresql+asyncpg://postgres@localhost:5432/gdev_test"
    _run_migration_test(local_url, monkeypatch)


def test_get_settings_accepts_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/db")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.database_url is not None
    get_settings.cache_clear()
