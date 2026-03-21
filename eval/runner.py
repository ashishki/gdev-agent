"""Minimal eval runner for gdev-agent."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import fakeredis
from app.agent import AgentService
from app.approval_store import RedisApprovalStore
from app.config import Settings
from app.cost_ledger import BudgetExhaustedError, CostLedger
from app.db import _set_tenant_ctx
from app.schemas import WebhookRequest
from app.store import EventStore

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

UTC = timezone.utc


def _build_default_agent() -> AgentService:
    settings = Settings()
    approval_store = RedisApprovalStore(fakeredis.FakeRedis(), ttl_seconds=settings.approval_ttl_seconds)
    return AgentService(
        settings=settings,
        store=EventStore(sqlite_path=None),
        approval_store=approval_store,
    )


def load_cases(path: Path) -> list[dict[str, Any]]:
    """Load JSONL eval cases from disk."""
    cases: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            raw = line.strip()
            if not raw:
                continue
            cases.append(json.loads(raw))
    return cases


def run_eval(cases_path: Path, agent: AgentService | None = None) -> dict[str, Any]:
    """Run cases through the agent and compute accuracy and guard metrics."""
    if agent is None:
        agent = _build_default_agent()

    per_label: dict[str, dict[str, int]] = {}
    total = 0
    correct = 0
    guard_blocks = 0
    expected_guard_count = 0
    correct_guard_blocks = 0

    for case in load_cases(cases_path):
        tenant_id_value = case.get("tenant_id")
        expected_guard = case.get("expected_guard")
        expected_category = case.get("expected_category")

        if expected_guard == "input_blocked":
            expected_guard_count += 1

        try:
            if tenant_id_value is not None:
                _run_sync_budget_check(agent, tenant_id_value)
            response = agent.process_webhook(
                WebhookRequest(
                    text=str(case["text"]),
                    user_id="eval-user",
                    tenant_id=str(tenant_id_value) if tenant_id_value is not None else None,
                )
            )
            predicted = response.classification.category
            blocked = False
        except BudgetExhaustedError as exc:
            return {
                "total": total,
                "correct": correct,
                "guard_blocks": guard_blocks,
                "accuracy": round(correct / total, 4) if total else 0.0,
                "guard_block_rate": (
                    1.0
                    if expected_guard_count == 0
                    else round(correct_guard_blocks / expected_guard_count, 4)
                ),
                "cost_usd": 0.0,
                "per_label_accuracy": {
                    label: round(stats["correct"] / stats["total"], 4)
                    if stats["total"]
                    else 0.0
                    for label, stats in per_label.items()
                },
                "status": "aborted_budget",
                "explanation": (
                    f"Daily budget exhausted at ${exc.current_usd} of ${exc.budget_usd}; "
                    "eval run aborted before the next LLM call."
                ),
            }
        except ValueError:
            predicted = None
            blocked = True

        if blocked:
            guard_blocks += 1
            if expected_guard == "input_blocked":
                correct_guard_blocks += 1
            continue

        if expected_category is None:
            continue

        expected = str(expected_category)
        per_label.setdefault(expected, {"correct": 0, "total": 0})
        per_label[expected]["total"] += 1
        total += 1

        if predicted == expected:
            correct += 1
            per_label[expected]["correct"] += 1

    per_label_accuracy = {
        label: round(stats["correct"] / stats["total"], 4) if stats["total"] else 0.0
        for label, stats in per_label.items()
    }
    guard_block_rate = 1.0 if expected_guard_count == 0 else round(correct_guard_blocks / expected_guard_count, 4)

    return {
        "total": total,
        "correct": correct,
        "guard_blocks": guard_blocks,
        "accuracy": round(correct / total, 4) if total else 0.0,
        "guard_block_rate": guard_block_rate,
        "cost_usd": 0.0,
        "per_label_accuracy": per_label_accuracy,
        "status": "completed",
    }


def _run_sync_budget_check(agent: AgentService, tenant_id_value: object) -> None:
    tenant_id = UUID(str(tenant_id_value))
    session_factory = getattr(agent.store, "_db_session_factory", None)
    if session_factory is None:
        return

    async def _check_budget() -> None:
        async with session_factory() as session:
            async with session.begin():
                await _set_tenant_ctx(session, str(tenant_id))
                await agent.cost_ledger.check_budget(tenant_id, session)

    asyncio.run(_check_budget())


async def run_eval_job(
    *,
    cases_path: Path,
    tenant_id: UUID,
    eval_run_id: UUID,
    db_session: AsyncSession,
    agent: AgentService | None = None,
) -> dict[str, Any]:
    """Run eval for one tenant and persist eval/cost records."""
    started_at = datetime.now(UTC)
    async with db_session.begin():
        await _set_tenant_ctx(db_session, str(tenant_id))
        await db_session.execute(
            text(
                """
                UPDATE eval_runs
                SET started_at = :started_at, status = :status
                WHERE eval_run_id = :eval_run_id AND tenant_id = :tenant_id
                """
            ),
            {
                "started_at": started_at,
                "status": "running",
                "eval_run_id": str(eval_run_id),
                "tenant_id": str(tenant_id),
            },
        )

    async with db_session.begin():
        await _set_tenant_ctx(db_session, str(tenant_id))
        prior_row = (
            await db_session.execute(
                text(
                    """
                    SELECT f1_score
                    FROM eval_runs
                    WHERE tenant_id = :tenant_id
                      AND eval_run_id != :eval_run_id
                      AND f1_score IS NOT NULL
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"tenant_id": str(tenant_id), "eval_run_id": str(eval_run_id)},
            )
        ).mappings().first()

    if agent is None:
        agent = _build_default_agent()

    cost_ledger = CostLedger()
    per_label: dict[str, dict[str, int]] = {}
    total = 0
    correct = 0
    guard_blocks = 0
    expected_guard_count = 0
    correct_guard_blocks = 0

    try:
        for case in load_cases(cases_path):
            async with db_session.begin():
                await _set_tenant_ctx(db_session, str(tenant_id))
                await cost_ledger.check_budget(tenant_id, db_session)

            expected_guard = case.get("expected_guard")
            expected_category = case.get("expected_category")

            if expected_guard == "input_blocked":
                expected_guard_count += 1

            try:
                response = agent.process_webhook(
                    WebhookRequest(text=str(case["text"]), user_id="eval-user")
                )
                predicted = response.classification.category
                blocked = False
            except ValueError:
                predicted = None
                blocked = True

            if blocked:
                guard_blocks += 1
                if expected_guard == "input_blocked":
                    correct_guard_blocks += 1
                continue

            if expected_category is None:
                continue

            expected = str(expected_category)
            per_label.setdefault(expected, {"correct": 0, "total": 0})
            per_label[expected]["total"] += 1
            total += 1

            if predicted == expected:
                correct += 1
                per_label[expected]["correct"] += 1
    except BudgetExhaustedError as exc:
        completed_at = datetime.now(UTC)
        async with db_session.begin():
            await _set_tenant_ctx(db_session, str(tenant_id))
            await db_session.execute(
                text(
                    """
                    UPDATE eval_runs
                    SET completed_at = :completed_at,
                        status = :status
                    WHERE eval_run_id = :eval_run_id AND tenant_id = :tenant_id
                    """
                ),
                {
                    "completed_at": completed_at,
                    "status": "aborted_budget",
                    "eval_run_id": str(eval_run_id),
                    "tenant_id": str(tenant_id),
                },
            )

        return {
            "total": total,
            "correct": correct,
            "guard_blocks": guard_blocks,
            "accuracy": round(correct / total, 4) if total else 0.0,
            "guard_block_rate": (
                1.0
                if expected_guard_count == 0
                else round(correct_guard_blocks / expected_guard_count, 4)
            ),
            "cost_usd": 0.0,
            "per_label_accuracy": {
                label: round(stats["correct"] / stats["total"], 4) if stats["total"] else 0.0
                for label, stats in per_label.items()
            },
            "eval_run_id": str(eval_run_id),
            "status": "aborted_budget",
            "regression_alert": False,
            "explanation": (
                f"Daily budget exhausted at ${exc.current_usd} of ${exc.budget_usd}; "
                "eval run aborted before the next LLM call."
            ),
        }

    report = {
        "total": total,
        "correct": correct,
        "guard_blocks": guard_blocks,
        "accuracy": round(correct / total, 4) if total else 0.0,
        "guard_block_rate": (
            1.0 if expected_guard_count == 0 else round(correct_guard_blocks / expected_guard_count, 4)
        ),
        "cost_usd": 0.0,
        "per_label_accuracy": {
            label: round(stats["correct"] / stats["total"], 4) if stats["total"] else 0.0
            for label, stats in per_label.items()
        },
    }
    current_f1 = Decimal(str(report["accuracy"]))
    prior_f1 = (
        Decimal(str(prior_row["f1_score"]))
        if prior_row and prior_row["f1_score"] is not None
        else None
    )
    regression_alert = bool(
        prior_f1 is not None and current_f1 < (prior_f1 - Decimal("0.02"))
    )
    status = "completed_with_regression" if regression_alert else "completed"
    completed_at = datetime.now(UTC)
    cost_usd = Decimal(str(report.get("cost_usd", 0.0)))

    async with db_session.begin():
        await _set_tenant_ctx(db_session, str(tenant_id))
        await db_session.execute(
            text(
                """
                UPDATE eval_runs
                SET completed_at = :completed_at,
                    f1_score = :f1_score,
                    guard_block_rate = :guard_block_rate,
                    cost_usd = :cost_usd,
                    status = :status
                WHERE eval_run_id = :eval_run_id AND tenant_id = :tenant_id
                """
            ),
            {
                "completed_at": completed_at,
                "f1_score": current_f1,
                "guard_block_rate": Decimal(str(report["guard_block_rate"])),
                "cost_usd": cost_usd,
                "status": status,
                "eval_run_id": str(eval_run_id),
                "tenant_id": str(tenant_id),
            },
        )
        await cost_ledger.record(
            tenant_id=tenant_id,
            day=date.today(),
            input_tokens=0,
            output_tokens=0,
            cost_usd=cost_usd,
            db=db_session,
        )

    report["eval_run_id"] = str(eval_run_id)
    report["status"] = status
    report["regression_alert"] = regression_alert
    return report


def main() -> None:
    """Run eval and print report as JSON."""
    cases_path = Path(__file__).with_name("cases.jsonl")
    report = run_eval(cases_path)
    results_dir = Path(__file__).resolve().parents[1] / "eval" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "last_run.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
