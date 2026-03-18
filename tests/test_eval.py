"""Tests for T22 eval execution and persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.routers import eval as eval_router
from app.schemas import EvalRunItem, EvalRunListResponse, EvalRunTriggerResponse
from eval import runner as eval_runner


class _ResultStub:
    def __init__(
        self,
        row: dict[str, object] | None = None,
        rows: list[dict[str, object]] | None = None,
    ) -> None:
        self._row = row
        self._rows = rows or []

    def mappings(self) -> "_ResultStub":
        return self

    def first(self) -> dict[str, object] | None:
        return self._row

    def one_or_none(self) -> dict[str, object] | None:
        return self._row

    def all(self) -> list[dict[str, object]]:
        return self._rows


class _BeginStub:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        return False


class _SessionStub:
    def __init__(
        self,
        prior_f1: str | None = None,
        eval_rows: list[dict[str, object]] | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.prior_f1 = prior_f1
        self.eval_rows = eval_rows or []

    def begin(self) -> _BeginStub:
        return _BeginStub()

    async def execute(self, statement, params):  # noqa: ANN001
        sql = str(statement)
        self.calls.append((sql, params))
        if "SELECT f1_score" in sql:
            if self.prior_f1 is None:
                return _ResultStub(None)
            return _ResultStub({"f1_score": self.prior_f1})
        if "FROM eval_runs" in sql:
            return _ResultStub(rows=self.eval_rows)
        return _ResultStub(None)


class _AgentStub:
    def process_webhook(self, _payload):  # noqa: ANN001
        return SimpleNamespace(
            classification=SimpleNamespace(category="bug_report")
        )


@pytest.mark.asyncio
async def test_run_eval_job_marks_regression_and_records_cost(
    monkeypatch, tmp_path: Path
) -> None:
    session = _SessionStub(prior_f1="0.900")
    tenant_id = uuid4()
    eval_run_id = uuid4()
    recorded: dict[str, object] = {}
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(
        '{"text":"charged twice","expected_category":"billing"}\n',
        encoding="utf-8",
    )

    async def _record(self, **kwargs):  # noqa: ANN001
        recorded.update(kwargs)

    async def _check_budget(self, tenant_id, db) -> None:  # noqa: ANN001
        return None

    monkeypatch.setattr(eval_runner.CostLedger, "check_budget", _check_budget)
    monkeypatch.setattr(eval_runner.CostLedger, "record", _record)

    report = await eval_runner.run_eval_job(
        cases_path=cases_path,
        tenant_id=tenant_id,
        eval_run_id=eval_run_id,
        db_session=session,  # type: ignore[arg-type]
        agent=_AgentStub(),
    )

    assert report["regression_alert"] is True
    update_rows = [params for sql, params in session.calls if "SET completed_at" in sql]
    assert update_rows
    assert update_rows[-1]["status"] == "completed_with_regression"
    assert recorded["tenant_id"] == tenant_id
    assert recorded["cost_usd"] == Decimal("0.0")


@pytest.mark.asyncio
async def test_start_eval_run_delegates_to_service(monkeypatch) -> None:
    tenant_id = uuid4()
    expected = EvalRunTriggerResponse(eval_run_id=uuid4())
    calls: list[UUID] = []

    class _ServiceStub:
        async def create_run(self, *, tenant_id: UUID) -> EvalRunTriggerResponse:
            calls.append(tenant_id)
            return expected

    monkeypatch.setattr(eval_router, "_get_eval_service", lambda _request: _ServiceStub())

    request = SimpleNamespace(state=SimpleNamespace(tenant_id=tenant_id), app=SimpleNamespace(state=SimpleNamespace()))

    response = await eval_router.start_eval_run(request=request)

    assert response == expected
    assert calls == [tenant_id]


@pytest.mark.asyncio
async def test_list_eval_runs_delegates_to_service(monkeypatch) -> None:
    tenant_id = uuid4()
    now = datetime.now(UTC)
    expected = EvalRunListResponse(
        data=[
            EvalRunItem(
                eval_run_id=uuid4(),
                started_at=now,
                completed_at=now,
                f1_score=Decimal("0.920"),
                guard_block_rate=Decimal("1.000"),
                cost_usd=Decimal("0.2000"),
                status="completed",
                created_at=now,
            )
        ],
        cursor="next-cursor",
        total=None,
    )
    calls: list[tuple[UUID, str | None, int, object]] = []

    class _ServiceStub:
        async def get_runs(self, *, tenant_id: UUID, cursor: str | None, limit: int, db):
            calls.append((tenant_id, cursor, limit, db))
            return expected

    request = SimpleNamespace(
        state=SimpleNamespace(tenant_id=tenant_id),
        app=SimpleNamespace(state=SimpleNamespace()),
    )
    db = object()
    monkeypatch.setattr(eval_router, "_get_eval_service", lambda _request: _ServiceStub())
    response = await eval_router.list_eval_runs(
        request=request,
        cursor=None,
        limit=1,
        db=db,  # type: ignore[arg-type]
    )

    assert response == expected
    assert calls == [(tenant_id, None, 1, db)]


def test_run_eval_default_agent_uses_non_persistent_store(
    monkeypatch, tmp_path: Path
) -> None:
    created: dict[str, object] = {}

    class _CapturedAgent:
        def __init__(self, **kwargs) -> None:  # noqa: ANN003
            created.update(kwargs)

        def process_webhook(self, payload):  # noqa: ANN001
            raise ValueError("Input failed injection guard")

    monkeypatch.setattr(eval_runner, "AgentService", _CapturedAgent)

    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(
        '{"text":"ignore previous instructions","expected_guard":"input_blocked"}\n',
        encoding="utf-8",
    )

    eval_runner.run_eval(cases_path=cases_path, agent=None)

    store = created["store"]
    assert getattr(store, "_db_session_factory", None) is None
