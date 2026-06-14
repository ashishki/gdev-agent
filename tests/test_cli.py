from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from click.testing import CliRunner

from scripts import cli, demo, seed_db

ROOT = Path(__file__).resolve().parents[1]


class _ResultStub:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self) -> "_ResultStub":
        return self

    def all(self) -> list[dict[str, object]]:
        return self._rows

    def first(self) -> dict[str, object] | None:
        return self._rows[0] if self._rows else None

    def one(self) -> dict[str, object]:
        return self._rows[0]

    def one_or_none(self) -> dict[str, object] | None:
        return self._rows[0] if self._rows else None


class _SessionStub:
    def __init__(self, rows_by_call: list[list[dict[str, object]]]) -> None:
        self.rows_by_call = rows_by_call
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def __aenter__(self) -> "_SessionStub":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    def begin(self) -> "_SessionStub":
        return self

    async def execute(self, statement, params):  # noqa: ANN001
        self.calls.append((str(statement), params))
        rows = self.rows_by_call.pop(0) if self.rows_by_call else []
        return _ResultStub(rows)


class _EngineStub:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


class _RedisStub:
    def __init__(self) -> None:
        self.deleted_keys: list[str] = []
        self.closed = False

    async def delete(self, key: str) -> None:
        self.deleted_keys.append(key)

    async def aclose(self) -> None:
        self.closed = True


def _patch_settings(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(cli, "_get_settings", lambda: SimpleNamespace(redis_url="redis://test"))


def _patch_session_bundle(monkeypatch, session: _SessionStub, engine: _EngineStub) -> None:  # noqa: ANN001
    monkeypatch.setattr(
        cli,
        "_session_bundle_from_settings",
        lambda settings: (engine, lambda: session),
    )


def test_help_lists_all_commands() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/cli.py"), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "tenant" in result.stdout
    assert "budget" in result.stdout
    assert "rca" in result.stdout
    assert "migrations" in result.stdout


def test_demo_command_surfaces_reviewer_transcript_and_help() -> None:
    demo_help = subprocess.run(
        [sys.executable, str(ROOT / "scripts/demo.py"), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    wrapper_help = subprocess.run(
        ["bash", str(ROOT / "scripts/demo.sh"), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    demo_source = (ROOT / "scripts" / "demo.py").read_text(encoding="utf-8")

    assert demo_help.returncode == 0
    assert "--llm-mode" in demo_help.stdout
    assert wrapper_help.returncode == 0
    assert "LLM_MODE=demo" in wrapper_help.stdout
    assert "demo:" in makefile
    assert "bash scripts/demo.sh" in makefile

    assert "Send signed webhook" in demo_source
    assert "Pending approval created" in demo_source
    assert "Approval decision status=approved" in demo_source
    assert "Metrics check" in demo_source
    assert "stack unavailable" in demo_source
    assert "verify docker/seed.sql was applied" in demo_source


def test_demo_seed_contract_matches_docs_and_defaults(monkeypatch) -> None:  # noqa: ANN001
    docs = (ROOT / "docs" / "DEMO.md").read_text(encoding="utf-8")
    seed_sql = (ROOT / "docker" / "seed.sql").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    for key in (
        "DEMO_TENANT_SLUG",
        "DEMO_TENANT_ID",
        "DEMO_WEBHOOK_SECRET",
        "DEMO_ADMIN_EMAIL",
        "DEMO_ADMIN_PASSWORD",
        "DEMO_APPROVE_SECRET",
        "DEMO_REVIEWER",
        "DEMO_LLM_MODE",
    ):
        monkeypatch.delenv(key, raising=False)

    config = demo.build_config(
        SimpleNamespace(
            url="http://localhost:8000",
            poll_interval=1.0,
            timeout=30.0,
            llm_mode="demo",
        )
    )

    primary_tenant = seed_db.DEMO_TENANTS[0]
    assert config.tenant_slug == primary_tenant["slug"]
    assert config.tenant_id == primary_tenant["tenant_id"]
    assert config.webhook_secret == primary_tenant["webhook_secret"]
    assert config.admin_email == primary_tenant["admin_email"]
    assert config.admin_password == primary_tenant["admin_password"]
    assert config.approve_secret == seed_db.DEMO_APPROVE_SECRET
    assert config.reviewer == seed_db.DEMO_REVIEWER
    assert config.llm_mode == "demo"

    assert f"APPROVE_SECRET: {seed_db.DEMO_APPROVE_SECRET}" in compose
    assert "python scripts/cli.py migrations check" in compose
    assert seed_db.DEMO_APPROVE_SECRET in docs
    assert seed_db.DEMO_REVIEWER in docs

    for tenant in seed_db.DEMO_TENANTS:
        assert tenant["slug"] in docs
        assert tenant["tenant_id"] in docs
        assert tenant["webhook_secret"] in docs
        assert tenant["admin_email"] in docs
        assert tenant["admin_password"] in docs

        assert tenant["slug"] in seed_sql
        assert tenant["tenant_id"] in seed_sql
        assert tenant["admin_email"] in seed_sql


def test_tenant_list_command(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    session = _SessionStub(
        [
            [
                {
                    "tenant_id": str(uuid4()),
                    "slug": "alpha",
                    "is_active": True,
                    "daily_budget_usd": "10.0",
                }
            ]
        ]
    )
    engine = _EngineStub()
    _patch_settings(monkeypatch)
    _patch_session_bundle(monkeypatch, session, engine)

    result = runner.invoke(cli.app, ["tenant", "list"])

    assert result.exit_code == 0
    assert "slug=alpha" in result.output
    assert engine.disposed is True


def test_tenant_create_command(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    tenant_id = uuid4()
    session = _SessionStub(
        [
            [
                {
                    "tenant_id": str(tenant_id),
                    "slug": "studio-a",
                    "is_active": True,
                    "daily_budget_usd": "12.5",
                }
            ],
            [],
        ]
    )
    engine = _EngineStub()
    redis = _RedisStub()
    tenant_ctx_calls: list[str] = []
    _patch_settings(monkeypatch)
    _patch_session_bundle(monkeypatch, session, engine)
    monkeypatch.setattr(cli, "uuid4", lambda: tenant_id)
    monkeypatch.setattr(cli, "_redis_client_from_settings", lambda settings: redis)

    async def _fake_set_tenant_ctx(session, tenant_id):  # noqa: ANN001
        _ = session
        tenant_ctx_calls.append(str(tenant_id))

    monkeypatch.setattr(cli, "_set_tenant_ctx", _fake_set_tenant_ctx)

    result = runner.invoke(
        cli.app,
        [
            "tenant",
            "create",
            "--name",
            "Studio A",
            "--slug",
            "studio-a",
            "--daily-budget-usd",
            "12.5",
        ],
    )

    assert result.exit_code == 0
    assert f"Created tenant {tenant_id}" in result.output
    assert redis.deleted_keys == [f"tenant:{tenant_id}:config"]
    assert redis.closed is True
    assert "INSERT INTO tenants" in session.calls[0][0]
    assert tenant_ctx_calls == [str(tenant_id)]


def test_tenant_disable_command(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    tenant_id = uuid4()
    session = _SessionStub([[], [{"tenant_id": str(tenant_id)}]])
    engine = _EngineStub()
    redis = _RedisStub()
    _patch_settings(monkeypatch)
    _patch_session_bundle(monkeypatch, session, engine)
    monkeypatch.setattr(cli, "_redis_client_from_settings", lambda settings: redis)

    result = runner.invoke(cli.app, ["tenant", "disable", str(tenant_id)])

    assert result.exit_code == 0
    assert f"Disabled tenant {tenant_id}" in result.output
    assert redis.deleted_keys == [f"tenant:{tenant_id}:config"]


def test_tenant_disable_command_not_found(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    tenant_id = uuid4()
    session = _SessionStub([[]])
    engine = _EngineStub()
    redis = _RedisStub()
    _patch_settings(monkeypatch)
    _patch_session_bundle(monkeypatch, session, engine)
    monkeypatch.setattr(cli, "_redis_client_from_settings", lambda settings: redis)

    result = runner.invoke(cli.app, ["tenant", "disable", str(tenant_id)])

    assert result.exit_code != 0
    assert f"Tenant not found: {tenant_id}" in result.output
    assert redis.deleted_keys == []


def test_budget_check_command(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    tenant_id = uuid4()
    session = _SessionStub([[], [{"budget_usd": "10.0", "current_usd": "2.5"}]])
    engine = _EngineStub()
    _patch_settings(monkeypatch)
    _patch_session_bundle(monkeypatch, session, engine)

    result = runner.invoke(cli.app, ["budget", "check", str(tenant_id)])

    assert result.exit_code == 0
    assert f"tenant_id={tenant_id}" in result.output
    assert "status=ok" in result.output


def test_budget_check_command_exhausted(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    tenant_id = uuid4()
    session = _SessionStub([[], [{"budget_usd": "10.0", "current_usd": "10.0"}]])
    engine = _EngineStub()
    _patch_settings(monkeypatch)
    _patch_session_bundle(monkeypatch, session, engine)

    result = runner.invoke(cli.app, ["budget", "check", str(tenant_id)])

    assert result.exit_code == 0
    assert "status=exhausted" in result.output


def test_budget_check_command_not_found(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    tenant_id = uuid4()
    session = _SessionStub([[], []])
    engine = _EngineStub()
    _patch_settings(monkeypatch)
    _patch_session_bundle(monkeypatch, session, engine)

    result = runner.invoke(cli.app, ["budget", "check", str(tenant_id)])

    assert result.exit_code != 0
    assert f"Tenant not found: {tenant_id}" in result.output


def test_budget_reset_command(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    tenant_id = uuid4()
    session = _SessionStub([[], [{"tenant_id": str(tenant_id)}]])
    engine = _EngineStub()
    _patch_settings(monkeypatch)
    _patch_session_bundle(monkeypatch, session, engine)

    result = runner.invoke(cli.app, ["budget", "reset", str(tenant_id)])

    assert result.exit_code == 0
    assert f"Reset budget for {tenant_id}; removed_rows=1" in result.output


def test_rca_run_command(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    tenant_id = uuid4()
    seen: list[str] = []
    _patch_settings(monkeypatch)

    async def _fake_run(settings, tenant: object) -> None:
        _ = settings
        seen.append(str(tenant))

    monkeypatch.setattr(cli, "_run_rca_for_tenant", _fake_run)

    result = runner.invoke(cli.app, ["rca", "run", str(tenant_id)])

    assert result.exit_code == 0
    assert seen == [str(tenant_id)]
    assert f"RCA run completed for {tenant_id}" in result.output


def test_migrations_check_command_reports_ok(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    session = _SessionStub([[{"version_num": "head-a"}]])
    engine = _EngineStub()
    monkeypatch.setattr(cli, "_get_migration_settings", lambda: SimpleNamespace())
    _patch_session_bundle(monkeypatch, session, engine)
    monkeypatch.setattr(cli, "_migration_heads", lambda: ("head-a",))

    result = runner.invoke(cli.app, ["migrations", "check"])

    assert result.exit_code == 0
    assert "migration_status=ok current=head-a heads=head-a" in result.output
    assert "FROM alembic_version" in session.calls[0][0]
    assert engine.disposed is True


def test_migrations_check_command_does_not_load_live_llm_settings(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    session = _SessionStub([[{"version_num": "head-a"}]])
    engine = _EngineStub()
    monkeypatch.setattr(cli, "_get_settings", lambda: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(cli, "_get_migration_settings", lambda: SimpleNamespace())
    _patch_session_bundle(monkeypatch, session, engine)
    monkeypatch.setattr(cli, "_migration_heads", lambda: ("head-a",))

    result = runner.invoke(cli.app, ["migrations", "check"])

    assert result.exit_code == 0
    assert "migration_status=ok current=head-a heads=head-a" in result.output


def test_migrations_check_command_fails_on_drift(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    session = _SessionStub([[{"version_num": "old-rev"}]])
    engine = _EngineStub()
    monkeypatch.setattr(cli, "_get_migration_settings", lambda: SimpleNamespace())
    _patch_session_bundle(monkeypatch, session, engine)
    monkeypatch.setattr(cli, "_migration_heads", lambda: ("head-a",))

    result = runner.invoke(cli.app, ["migrations", "check"])

    assert result.exit_code != 0
    assert "migration_status=drift current=old-rev heads=head-a" in result.output
