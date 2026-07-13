import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_harness_docs_are_linked_and_define_boundaries() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    harness = (ROOT / "docs/HARNESS_CARD.md").read_text(encoding="utf-8")
    trace = (ROOT / "docs/TRACE_SCHEMA.md").read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    eval_scope = (ROOT / "docs/EVAL_SCOPE_RECONCILIATION.md").read_text(encoding="utf-8")

    assert "docs/HARNESS_CARD.md" in readme
    assert "img.shields.io" not in readme
    assert "## Current Maturity" in readme
    assert "## Relationship to the Portfolio" in readme
    assert "## Product Boundary and Non-Goals" in readme
    assert "pilot-grade" not in readme
    assert "github.com/your-handle" not in readme
    assert "model + prompt/tool loop + guards + approvals + trace + eval" in harness
    assert "No autonomous long-term memory" in harness
    assert "gdev-agent-trace-v1" in trace
    assert "No Silent Workaround Policy" in agents
    assert "0e4c5f0fd50382bbf12ffd35cfca4632384fb0cc" in eval_scope
    assert "Gate **FAIL**" in eval_scope
    assert "sha256:656face21f27b496d4d3e8bb0b588824f5737d122c1275c710f3e5b15ff94b4b" in eval_scope


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


def test_maintainer_intake_is_private_bounded_and_reproducible() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    bug_form = (ROOT / ".github/ISSUE_TEMPLATE/reproducible-bug.yml").read_text(encoding="utf-8")
    issue_config = (ROOT / ".github/ISSUE_TEMPLATE/config.yml").read_text(encoding="utf-8")

    private_path = "https://github.com/ashishki/gdev-agent/security/advisories/new"
    assert private_path in security
    assert private_path in issue_config
    assert "Do **not** open a public issue" in security
    assert "Current `master` at an identified commit SHA" in security
    assert "no tagged stable product release" in security
    assert "cannot promise a response or fix deadline" in security

    assert "Exact commit SHA" in bug_form
    assert "Reproduction commands" in bug_form
    assert "synthetic or sanitized data" in bug_form
    assert "not a feature or hosted-product roadmap request" in bug_form
    assert "blank_issues_enabled: false" in issue_config
    assert not list((ROOT / ".github/ISSUE_TEMPLATE").glob("*feature*"))

    assert "## Maintainer Paths" in readme
    assert "SECURITY.md" in readme
    assert "reproducible-bug.yml" in readme


def test_visual_evidence_surfaces_are_pinned_and_bounded() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    evidence_index = (ROOT / "docs/EVIDENCE_INDEX.md").read_text(encoding="utf-8")
    approval = (ROOT / "docs/APPROVAL_FLOW.md").read_text(encoding="utf-8")
    preview = (ROOT / "docs/evidence/GDEV_EVAL_FAILURE_PREVIEW_2026-07-13.md").read_text(
        encoding="utf-8"
    )
    svg_path = ROOT / "docs/assets/gdev-eval-lab-challenge-fail.svg"
    svg = svg_path.read_text(encoding="utf-8")

    for path in (
        "docs/APPROVAL_FLOW.md",
        "docs/evidence/GDEV_EVAL_FAILURE_PREVIEW_2026-07-13.md",
        "docs/assets/gdev-eval-lab-challenge-fail.svg",
    ):
        assert path in readme

    assert "AgentService.needs_approval()" in approval
    assert "RedisApprovalStore" in approval
    assert "Atomic GETDEL" in approval
    assert "tests/test_approval_flow.py" in approval
    assert "implemented approval mechanics do not imply" in approval

    content_address = "sha256:656face21f27b496d4d3e8bb0b588824f5737d122c1275c710f3e5b15ff94b4b"
    component_revision = "0e4c5f0fd50382bbf12ffd35cfca4632384fb0cc"
    summary_hash = "d4bb0dec70d75de8d33d16f583a01ecbc17bf202ae04509d3dec63087a7b3a3b"
    svg_hash = "091ad0ad87bab99b8216603f57ef79266ce6f9950ed33a77a4167f04a58ec770"

    for claim in (content_address, component_revision, summary_hash):
        assert claim in preview
        assert claim in svg
    assert content_address in evidence_index
    assert "challenge gate is **FAIL**" in preview
    assert "90 candidate HTTP calls" in preview
    assert "10 labeled deterministic" in preview
    assert "not a rerun" in preview
    assert "--check" in preview
    assert hashlib.sha256(svg_path.read_bytes()).hexdigest() == svg_hash

    renderer = (ROOT / "scripts/render_eval_failure_preview.py").read_text(encoding="utf-8")
    assert "manifest does not match the pinned canonical digest" in renderer
    assert "manifest does not match the pinned content address" in renderer
    assert "challenge-run.json does not match its manifest digest" in renderer
    assert "this renderer only accepts a recorded failed gate" in renderer
