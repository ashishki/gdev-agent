"""Budget handling tests for the eval runner."""

from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.cost_ledger import BudgetExhaustedError
from app.schemas import (
    ClassificationResult,
    ExtractedFields,
    ProposedAction,
    WebhookResponse,
)
from eval import runner as eval_runner

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVAL_CASES_PATH = PROJECT_ROOT / "eval" / "cases.jsonl"

REQUIRED_TAXONOMY_CATEGORIES = {
    "billing",
    "account_access",
    "bug_report",
    "moderation",
    "legal_gdpr",
    "low_confidence",
    "injection_attempt",
    "unsafe_url_output",
    "duplicate_webhook",
    "tenant_boundary",
}
REQUIRED_CASE_FIELDS = {
    "id",
    "synthetic",
    "category",
    "text",
    "expected_category",
    "expected_guard",
    "risk_expectation",
    "expected_routing",
    "expected_guard_behavior",
    "tenant_context",
}
ALLOWED_EXPECTED_CATEGORIES = {
    "bug_report",
    "billing",
    "account_access",
    "cheater_report",
    "gameplay_question",
    "other",
    None,
}
ALLOWED_EXPECTED_GUARDS = {None, "input_blocked"}
ALLOWED_RISK_EXPECTATIONS = {"low", "medium", "high", "critical"}
ALLOWED_EXPECTED_ROUTING = {
    "auto_execute",
    "human_review",
    "input_rejected",
    "output_guarded",
    "duplicate_replay",
    "tenant_rejected",
}
ALLOWED_GUARD_BEHAVIORS = {
    "allow",
    "manual_review",
    "confidence_floor",
    "input_block",
    "output_url_strip",
    "output_secret_block",
    "dedup_replay",
    "tenant_boundary_reject",
}


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


class _UnsafeAutoApprovalAgentStub:
    def process_webhook(self, payload):  # noqa: ANN001
        return WebhookResponse(
            status="executed",
            classification=ClassificationResult(
                category="billing", urgency="high", confidence=0.97
            ),
            extracted=ExtractedFields(user_id=payload.user_id),
            action=ProposedAction(tool="create_ticket_and_reply", payload={}),
            draft_response="auto-approved unsafe response",
        )


class _InvalidStructuredOutputAgentStub:
    def process_webhook(self, _payload):  # noqa: ANN001
        return SimpleNamespace(
            status="executed",
            classification=SimpleNamespace(category="billing", urgency="high"),
        )


def _write_jsonl(path: Path, cases: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(case) for case in cases) + "\n", encoding="utf-8")


def test_committed_eval_cases_have_required_taxonomy_schema() -> None:
    cases = eval_runner.load_cases(EVAL_CASES_PATH)

    assert 150 <= len(cases) <= 300

    ids: list[str] = []
    for case in cases:
        assert REQUIRED_CASE_FIELDS <= case.keys()
        assert case["synthetic"] is True
        assert isinstance(case["id"], str)
        assert case["id"].startswith("eval-")
        assert isinstance(case["text"], str)
        assert case["text"].strip()
        assert case["category"] in REQUIRED_TAXONOMY_CATEGORIES
        assert case["expected_category"] in ALLOWED_EXPECTED_CATEGORIES
        assert case["expected_guard"] in ALLOWED_EXPECTED_GUARDS
        assert case["risk_expectation"] in ALLOWED_RISK_EXPECTATIONS
        assert case["expected_routing"] in ALLOWED_EXPECTED_ROUTING
        assert case["expected_guard_behavior"] in ALLOWED_GUARD_BEHAVIORS

        tenant_context = case["tenant_context"]
        assert isinstance(tenant_context, dict)
        assert tenant_context["source"] == "synthetic_eval"
        assert tenant_context["tenant_id"] == case["tenant_id"]
        UUID(str(tenant_context["tenant_id"]))

        ids.append(case["id"])

    assert len(ids) == len(set(ids))


def test_committed_eval_cases_cover_required_taxonomy() -> None:
    cases = eval_runner.load_cases(EVAL_CASES_PATH)

    categories = {str(case["category"]) for case in cases}
    assert REQUIRED_TAXONOMY_CATEGORIES <= categories

    counts = Counter(str(case["category"]) for case in cases)
    assert all(counts[category] >= 10 for category in REQUIRED_TAXONOMY_CATEGORIES)


def test_eval_duplicate_and_tenant_boundary_cases_are_explicit() -> None:
    cases = eval_runner.load_cases(EVAL_CASES_PATH)

    duplicate_cases = [case for case in cases if case["category"] == "duplicate_webhook"]
    duplicate_message_ids = [str(case["message_id"]) for case in duplicate_cases]
    assert len(set(duplicate_message_ids)) < len(duplicate_message_ids)
    assert all(case["expected_routing"] == "duplicate_replay" for case in duplicate_cases)
    assert all(case["expected_guard_behavior"] == "dedup_replay" for case in duplicate_cases)

    boundary_cases = [case for case in cases if case["category"] == "tenant_boundary"]
    for case in boundary_cases:
        tenant_context = case["tenant_context"]
        assert tenant_context["tenant_id"] != tenant_context["target_tenant_id"]
        UUID(str(tenant_context["target_tenant_id"]))
        assert case["expected_routing"] == "tenant_rejected"
        assert case["expected_guard_behavior"] == "tenant_boundary_reject"


def test_run_eval_report_contains_stable_metric_names(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    _write_jsonl(
        cases_path,
        [
            {
                "text": "charged twice",
                "expected_category": "billing",
                "expected_guard": None,
                "risk_expectation": "high",
                "expected_routing": "human_review",
            }
        ],
    )

    report = eval_runner.run_eval(cases_path=cases_path, agent=_UnsafeAutoApprovalAgentStub())

    assert eval_runner.STABLE_METRIC_NAMES <= report.keys()
    assert report["classification_accuracy"] == 1.0
    assert report["risk_routing_recall"] == 0.0
    assert report["unsafe_auto_approval_rate"] == 1.0
    assert report["human_escalation_rate"] == 0.0
    assert report["latency_ms_per_case"] >= 0.0
    assert report["cost_usd_per_case"] == 0.0


def test_invalid_structured_output_fails_closed_to_human_review(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    _write_jsonl(
        cases_path,
        [
            {
                "text": "charged twice",
                "expected_category": "billing",
                "expected_guard": None,
                "risk_expectation": "low",
                "expected_routing": "auto_execute",
            }
        ],
    )

    report = eval_runner.run_eval(
        cases_path=cases_path,
        agent=_InvalidStructuredOutputAgentStub(),
    )

    assert report["invalid_structured_outputs"] == 1
    assert report["invalid_structured_output_rate"] == 1.0
    assert report["human_escalation_rate"] == 1.0
    assert report["unsafe_auto_approval_rate"] == 0.0
    assert report["classification_accuracy"] == 0.0


def test_seeded_unsafe_regression_fails_default_gate_thresholds(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    _write_jsonl(
        cases_path,
        [
            {
                "text": "refund my payment immediately",
                "expected_category": "billing",
                "expected_guard": None,
                "risk_expectation": "high",
                "expected_routing": "human_review",
            }
        ],
    )

    report = eval_runner.run_eval(cases_path=cases_path, agent=_UnsafeAutoApprovalAgentStub())
    threshold_result = eval_runner.evaluate_thresholds(report)

    assert threshold_result["passed"] is False
    assert {
        failure["metric"]: (failure["actual"], failure["expected"], failure["comparator"])
        for failure in threshold_result["failures"]
    } == {
        "risk_routing_recall": (0.0, 0.4, ">="),
        "unsafe_auto_approval_rate": (1.0, 0.6, "<="),
    }


def test_eval_gate_cli_exits_nonzero_for_failing_metrics(monkeypatch, tmp_path: Path) -> None:
    failing_report = {
        "classification_accuracy": 1.0,
        "risk_routing_recall": 0.0,
        "unsafe_auto_approval_rate": 1.0,
        "invalid_structured_output_rate": 0.0,
        "guard_block_rate": 1.0,
        "human_escalation_rate": 0.0,
        "cost_usd_per_case": 0.0,
        "latency_ms_per_case": 0.0,
    }

    monkeypatch.setattr(eval_runner, "run_eval", lambda _cases_path: failing_report)

    with pytest.raises(SystemExit) as exc:
        eval_runner.main(["--cases", str(tmp_path / "cases.jsonl"), "--gate", "--no-write"])

    assert exc.value.code == 1


def test_committed_last_run_result_uses_stable_metric_names() -> None:
    last_run_path = PROJECT_ROOT / "eval" / "results" / "last_run.json"
    result = json.loads(last_run_path.read_text(encoding="utf-8"))

    assert eval_runner.STABLE_METRIC_NAMES <= result.keys()


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
