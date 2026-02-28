"""Minimal eval runner for gdev-agent."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agent import AgentService
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


def run_eval(cases_path: Path) -> dict[str, Any]:
    """Run cases through the agent and compute per-label accuracy."""
    settings = Settings()
    store = EventStore(sqlite_path=None)
    agent = AgentService(settings=settings, store=store)

    per_label: dict[str, dict[str, int]] = {}
    total = 0
    correct = 0

    for case in load_cases(cases_path):
        expected = str(case["expected_category"])
        per_label.setdefault(expected, {"correct": 0, "total": 0})

        total += 1
        per_label[expected]["total"] += 1

        try:
            response = agent.process_webhook(WebhookRequest(text=str(case["text"])))
            predicted = response.classification.category
        except ValueError:
            predicted = "other"

        if predicted == expected:
            correct += 1
            per_label[expected]["correct"] += 1

    per_label_accuracy = {
        label: round(stats["correct"] / stats["total"], 4) if stats["total"] else 0.0
        for label, stats in per_label.items()
    }

    return {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 4) if total else 0.0,
        "per_label_accuracy": per_label_accuracy,
    }


def main() -> None:
    """Run eval and print report as JSON."""
    cases_path = Path(__file__).with_name("cases.jsonl")
    report = run_eval(cases_path)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
