from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from click.testing import CliRunner

from scripts import cli

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


def test_tenant_list_command(monkeypatch) -> None:  # noqa: ANN001
    runner = CliRunner()
    session = _SessionStub(
        [[{"tenant_id": str(uuid4()), "slug": "alpha", "is_active": True, "daily_budget_usd": "10.0"}]]
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
            [],
            [{"tenant_id": str(tenant_id), "slug": "studio-a", "is_active": True, "daily_budget_usd": "12.5"}],
        ]
    )
    engine = _EngineStub()
    redis = _RedisStub()
    _patch_settings(monkeypatch)
    _patch_session_bundle(monkeypatch, session, engine)
    monkeypatch.setattr(cli, "_redis_client_from_settings", lambda settings: redis)

    result = runner.invoke(
        cli.app,
        ["tenant", "create", "--name", "Studio A", "--slug", "studio-a", "--daily-budget-usd", "12.5"],
    )

    assert result.exit_code == 0
    assert f"Created tenant {tenant_id}" in result.output
    assert redis.deleted_keys == [f"tenant:{tenant_id}:config"]
    assert redis.closed is True


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
