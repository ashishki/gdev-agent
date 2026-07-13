from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/ci.yml"


def test_ci_actions_are_immutable_and_least_privilege() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    action_refs = re.findall(r"uses:\s*([^@\s]+)@([^\s#]+)", workflow)

    assert action_refs
    assert all(re.fullmatch(r"[0-9a-f]{40}", revision) for _, revision in action_refs)
    assert "\npermissions:\n  contents: read\n" in workflow
    checkout_count = sum(action == "actions/checkout" for action, _ in action_refs)
    assert checkout_count == 2
    assert workflow.count("persist-credentials: false") == checkout_count
