"""Budget handling tests for the eval runner."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from app.cost_ledger import BudgetExhaustedError
from app.schemas import (
    ClassificationResult,
    ExtractedFields,
    ProposedAction,
    WebhookResponse,
)
from eval import runner as eval_runner


class _ResultStub:
    def __init__(self, row: dict[str, object] | None = None) -> None:
        self._row = row

    def mappings(self) -> "_ResultStub":
        return self

    def first(self) -> dict[str, object] | None:
        return self._row


class _BeginStub:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        return False


class _SessionStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def begin(self) -> _BeginStub:
        return _BeginStub()

    async def execute(self, statement, params):  # noqa: ANN001
        sql = str(statement)
        self.calls.append((sql, params))
        if "SELECT f1_score" in sql:
            return _ResultStub(None)
        return _ResultStub(None)


class _AgentStub:
    def __init__(self) -> None:
        self.calls = 0

    def process_webhook(self, payload):  # noqa: ANN001
        self.calls += 1
        return WebhookResponse(
            status="executed",
            classification=ClassificationResult(category="billing", urgency="low", confidence=0.9),
            extracted=ExtractedFields(user_id="eval-user"),
            action=ProposedAction(tool="create_ticket_and_reply", payload={}),
            draft_response=payload.text,
        )


@pytest.mark.asyncio
async def test_run_eval_job_aborts_when_budget_exhausted(monkeypatch, tmp_path: Path) -> None:
    cases = [
        {"id": 1, "text": "charged twice", "expected_category": "billing"},
        {"id": 2, "text": "charged again", "expected_category": "billing"},
    ]
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text("\n".join(json.dumps(case) for case in cases) + "\n", encoding="utf-8")

    session = _SessionStub()
    agent = _AgentStub()
    tenant_id = uuid4()
    eval_run_id = uuid4()
    budget_checks = {"count": 0}

    async def _check_budget(self, tenant_id, db) -> None:  # noqa: ANN001
        budget_checks["count"] += 1
        if budget_checks["count"] == 2:
            raise BudgetExhaustedError(
                tenant_id=tenant_id,
                current_usd=Decimal("10.00"),
                budget_usd=Decimal("10.00"),
            )

    async def _record(self, **kwargs) -> None:  # noqa: ANN001
        raise AssertionError("record() should not run after budget exhaustion")

    monkeypatch.setattr(eval_runner.CostLedger, "check_budget", _check_budget)
    monkeypatch.setattr(eval_runner.CostLedger, "record", _record)

    report = await eval_runner.run_eval_job(
        cases_path=cases_path,
        tenant_id=tenant_id,
        eval_run_id=eval_run_id,
        db_session=session,  # type: ignore[arg-type]
        agent=agent,
    )

    assert budget_checks["count"] == 2
    assert agent.calls == 1
    assert report["status"] == "aborted_budget"
    assert "budget exhausted" in report["explanation"].lower()
    update_rows = [params for sql, params in session.calls if "SET completed_at" in sql]
    assert update_rows
    assert update_rows[-1]["status"] == "aborted_budget"
