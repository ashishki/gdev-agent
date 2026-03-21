"""Unit tests for EvalService."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.cost_ledger import BudgetExhaustedError
from app.services import eval_service as eval_service_module
from app.services.eval_service import EvalService, InvalidCursorError


UTC = timezone.utc

@dataclass
class _RecordedSpan:
    name: str
    attributes: dict[str, object] = field(default_factory=dict)
    exceptions: list[BaseException] = field(default_factory=list)

    def __enter__(self) -> "_RecordedSpan":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value

    def record_exception(self, exc: BaseException) -> None:
        self.exceptions.append(exc)


class _RecordingTracer:
    def __init__(self) -> None:
        self.spans: list[_RecordedSpan] = []

    def start_as_current_span(self, name: str) -> _RecordedSpan:
        span = _RecordedSpan(name=name)
        self.spans.append(span)
        return span


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

    def all(self) -> list[dict[str, object]]:
        return self._rows


class _SessionStub:
    def __init__(
        self,
        *,
        row: dict[str, object] | None = None,
        rows: list[dict[str, object]] | None = None,
    ) -> None:
        self.row = row
        self.rows = rows or []
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def __aenter__(self) -> "_SessionStub":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def begin(self) -> "_SessionStub":
        return self

    async def execute(self, statement, params):
        sql = str(statement)
        self.calls.append((sql, params))
        if "LIMIT 1" in sql and "FROM eval_runs" in sql:
            return _ResultStub(row=self.row)
        if "FROM eval_runs" in sql:
            return _ResultStub(rows=self.rows)
        return _ResultStub()


class _SessionFactoryStub:
    def __init__(self, sessions: list[_SessionStub]) -> None:
        self._sessions = sessions
        self.calls = 0

    def __call__(self) -> _SessionStub:
        session = self._sessions[min(self.calls, len(self._sessions) - 1)]
        self.calls += 1
        return session


class _BudgetLedgerStub:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def check_budget(self, tenant_id, db) -> None:  # noqa: ANN001
        _ = db
        self.calls.append(str(tenant_id))


class _BlockingBudgetLedgerStub:
    async def check_budget(self, tenant_id, db) -> None:  # noqa: ANN001
        _ = tenant_id, db
        raise BudgetExhaustedError(tenant_id=uuid4(), current_usd="10.0", budget_usd="10.0")


@pytest.mark.asyncio
async def test_create_run_inserts_row_starts_span_and_checks_budget_before_scheduling(
    monkeypatch, tmp_path: Path
) -> None:
    tracer = _RecordingTracer()
    tenant_id = uuid4()
    insert_session = _SessionStub()
    budget_session = _SessionStub()
    session_factory = _SessionFactoryStub([insert_session, budget_session])
    budget_ledger = _BudgetLedgerStub()
    scheduled: list[object] = []

    def _schedule(coro):
        assert budget_ledger.calls == [str(tenant_id)]
        scheduled.append(coro)
        coro.close()
        return SimpleNamespace()

    monkeypatch.setattr(eval_service_module, "TRACER", tracer)
    service = EvalService(
        db_session_factory=session_factory,
        cases_path=tmp_path / "cases.jsonl",
        cost_ledger=budget_ledger,  # type: ignore[arg-type]
        task_scheduler=_schedule,
    )

    response = await service.create_run(tenant_id=tenant_id)

    assert response.eval_run_id is not None
    assert any("INSERT INTO eval_runs" in sql for sql, _ in insert_session.calls)
    assert budget_ledger.calls == [str(tenant_id)]
    assert scheduled
    assert tracer.spans[0].name == "service.eval.create_run"
    assert (
        tracer.spans[0].attributes["tenant_id_hash"]
        == hashlib.sha256(str(tenant_id).encode("utf-8")).hexdigest()[:16]
    )


@pytest.mark.asyncio
async def test_create_run_marks_budget_block_without_scheduling(monkeypatch) -> None:
    tracer = _RecordingTracer()
    tenant_id = uuid4()
    insert_session = _SessionStub()
    budget_session = _SessionStub()
    update_session = _SessionStub()
    session_factory = _SessionFactoryStub([insert_session, budget_session, update_session])
    scheduled: list[object] = []

    def _schedule(coro):
        scheduled.append(coro)
        coro.close()
        return SimpleNamespace()

    monkeypatch.setattr(eval_service_module, "TRACER", tracer)
    service = EvalService(
        db_session_factory=session_factory,
        cost_ledger=_BlockingBudgetLedgerStub(),  # type: ignore[arg-type]
        task_scheduler=_schedule,
    )

    response = await service.create_run(tenant_id=tenant_id)

    assert response.eval_run_id is not None
    assert not scheduled
    assert any("SET status = :status, completed_at = :completed_at" in sql for sql, _ in update_session.calls)
    assert tracer.spans[0].name == "service.eval.create_run"


@pytest.mark.asyncio
async def test_get_runs_returns_paginated_rows_with_span(monkeypatch) -> None:
    tracer = _RecordingTracer()
    tenant_id = uuid4()
    now = datetime.now(UTC)
    session = _SessionStub(
        rows=[
            {
                "eval_run_id": uuid4(),
                "started_at": now,
                "completed_at": now,
                "f1_score": "0.920",
                "guard_block_rate": "1.000",
                "cost_usd": "0.2000",
                "status": "completed",
                "created_at": now,
            },
            {
                "eval_run_id": uuid4(),
                "started_at": now - timedelta(minutes=1),
                "completed_at": now - timedelta(minutes=1),
                "f1_score": "0.900",
                "guard_block_rate": "1.000",
                "cost_usd": "0.2100",
                "status": "completed",
                "created_at": now - timedelta(minutes=1),
            },
        ]
    )

    monkeypatch.setattr(eval_service_module, "TRACER", tracer)
    service = EvalService(db_session_factory=lambda: _SessionStub())

    response = await service.get_runs(tenant_id=tenant_id, cursor=None, limit=1, db=session)

    assert len(response.data) == 1
    assert response.cursor is not None
    assert tracer.spans[0].name == "service.eval.get_runs"
    assert tracer.spans[0].attributes["limit"] == 1


@pytest.mark.asyncio
async def test_get_runs_rejects_invalid_cursor(monkeypatch) -> None:
    monkeypatch.setattr(eval_service_module, "TRACER", _RecordingTracer())
    service = EvalService(db_session_factory=lambda: _SessionStub())

    with pytest.raises(InvalidCursorError):
        await service.get_runs(
            tenant_id=uuid4(),
            cursor="not-a-timestamp",
            limit=10,
            db=_SessionStub(),
        )


@pytest.mark.asyncio
async def test_get_run_status_returns_row_and_records_span(monkeypatch) -> None:
    tracer = _RecordingTracer()
    tenant_id = uuid4()
    eval_run_id = uuid4()
    now = datetime.now(UTC)
    session = _SessionStub(
        row={
            "eval_run_id": eval_run_id,
            "started_at": now,
            "completed_at": now,
            "f1_score": "0.920",
            "guard_block_rate": "1.000",
            "cost_usd": "0.2000",
            "status": "completed",
            "created_at": now,
        }
    )

    monkeypatch.setattr(eval_service_module, "TRACER", tracer)
    service = EvalService(db_session_factory=lambda: _SessionStub())

    result = await service.get_run_status(
        tenant_id=tenant_id,
        eval_run_id=eval_run_id,
        db=session,
    )

    assert result is not None
    assert result.eval_run_id == eval_run_id
    assert tracer.spans[0].name == "service.eval.get_run_status"
    assert tracer.spans[0].attributes["eval_run_id"] == str(eval_run_id)
