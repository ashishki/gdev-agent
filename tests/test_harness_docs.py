import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_harness_docs_are_linked_and_define_boundaries() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    harness = (ROOT / "docs/HARNESS_CARD.md").read_text(encoding="utf-8")
    trace = (ROOT / "docs/TRACE_SCHEMA.md").read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "docs/HARNESS_CARD.md" in readme
    assert "model + prompt/tool loop + guards + approvals + trace + eval" in harness
    assert "No autonomous long-term memory" in harness
    assert "gdev-agent-trace-v1" in trace
    assert "No Silent Workaround Policy" in agents


def test_harness_regression_fixture_is_synthetic_and_trace_oriented() -> None:
    cases_path = ROOT / "eval/harness_regression.jsonl"
    cases = [
        json.loads(line)
        for line in cases_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert len(cases) >= 6
    assert all(case["synthetic"] is True for case in cases)
    assert {case["slice"] for case in cases} >= {
        "ambiguous_ticket",
        "prompt_injection",
        "billing_refund",
        "legal_gdpr",
        "unsafe_output",
        "tenant_boundary",
    }
    assert all(case["expected_trace_events"] for case in cases)
    assert all(case["expected_route"] != "auto_execute" for case in cases)
