# ARCH_REPORT — Cycle 14
_Date: 2026-06-12_

## Component Verdicts

| Component | Verdict | Note |
|-----------|---------|------|
| Eval dataset | PASS | `eval/cases.jsonl` now has 180 synthetic cases across the required taxonomy. |
| Eval runner metrics | PASS | `eval/runner.py` emits stable metrics and fail-closed structured output handling. |
| Eval CI gate | PASS | CI runs `python -m eval.runner --gate --no-write` in demo mode after tests. |
| Eval architecture docs | DRIFT | `docs/ARCHITECTURE.md` still references the old 25-case/basic metric shape. |
| Phase 3 task plan | PASS | T11–T14 reinforce reliability and failure-mode proof without product expansion. |

## ADR Compliance

| ADR | Verdict | Note |
|-----|---------|------|
| ADR-001 Storage | PASS | Eval persistence remains in Postgres; file dataset is version-controlled synthetic data. |
| ADR-002 Vector DB | PASS | No vector-store changes in Phase 2. |
| ADR-003 RBAC | PASS | Eval APIs remain service-backed; Phase 3 cross-tenant tests align with JWT/RLS design. |
| ADR-004 Observability | PASS | Phase 3 will map failure modes to logs/metrics/traces; no contradiction introduced. |
| ADR-005 Orchestration | PASS | Eval runner remains on-demand/background, with no new scheduler model. |
| ADR-006 MCP | PASS | No new assistant-facing protocol surface was added. |

## Architecture Findings

### ARCH-HARDEN-1 [P2] — Architecture Eval Section Is Stale

Symptom: The architecture overview still says the eval dataset has 25 cases and describes the
runner as accuracy/per-label/guard-only, while Phase 2 implemented a 180-case taxonomy,
deterministic validators, baseline metrics, and a CI gate.

Evidence: `docs/ARCHITECTURE.md:73`, `docs/ARCHITECTURE.md:131`,
`docs/ARCHITECTURE.md:132`, `docs/ARCHITECTURE.md:277-296`

Root cause: T07–T10 intentionally scoped documentation updates to `docs/EVALUATION.md`,
`docs/EVAL_REPORT.md`, README, and the evidence index; architecture summary was outside those
task scopes.

Impact: Reviewers starting from architecture may see stale eval size/metric claims before reaching
the current eval guide/report.

Fix: Update the architecture feature table, repository layout, and Eval Subsystem section to
reference 180 cases, stable metric names, threshold gating, and the baseline report.

## Doc Patches Needed

| File | Section | Change |
|------|---------|--------|
| `docs/ARCHITECTURE.md` | Feature table / repo layout / Eval Subsystem | Replace 25-case/basic runner language with the current 180-case taxonomy, stable metrics, and CI gate. |
