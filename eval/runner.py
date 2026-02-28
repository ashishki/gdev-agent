"""Minimal eval runner for gdev-agent."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fakeredis

from app.agent import AgentService
from app.approval_store import RedisApprovalStore
from app.config import Settings
from app.schemas import WebhookRequest
from app.store import EventStore


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
        settings = Settings()
        approval_store = RedisApprovalStore(fakeredis.FakeRedis(), ttl_seconds=settings.approval_ttl_seconds)
        agent = AgentService(settings=settings, store=EventStore(sqlite_path=None), approval_store=approval_store)

    per_label: dict[str, dict[str, int]] = {}
    total = 0
    correct = 0
    guard_blocks = 0
    expected_guard_count = 0
    correct_guard_blocks = 0

    for case in load_cases(cases_path):
        expected_guard = case.get("expected_guard")
        expected_category = case.get("expected_category")

        if expected_guard == "input_blocked":
            expected_guard_count += 1

        try:
            response = agent.process_webhook(WebhookRequest(text=str(case["text"]), user_id="eval-user"))
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
        "per_label_accuracy": per_label_accuracy,
    }


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
