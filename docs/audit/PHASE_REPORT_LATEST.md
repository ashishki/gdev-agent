# Phase Report - Portfolio Hardening Phase 2

Date: 2026-06-12

## What Was Built

Phase 2 hardened the evaluation system so reviewers can inspect quality claims with committed data
and reproducible commands instead of relying on a single aggregate score.

- The eval dataset now contains 180 synthetic cases across billing, account access, bug reports,
  moderation, legal/GDPR, low-confidence handling, prompt injection, unsafe output, duplicate
  webhook, and tenant-boundary categories.
- The eval runner now emits stable metrics for classification accuracy, risk routing, unsafe
  auto-approval, invalid structured output, guard blocks, human escalation, cost, and latency.
- Structured output validation fails closed into human review when required fields are malformed or
  missing.
- The baseline eval report documents the current metrics, thresholds, command, assumptions, and
  known limits.
- CI now runs the lightweight eval gate in deterministic demo mode.

## Why It Matters

The project is a portfolio-grade reliability system, not a production SaaS. Phase 2 makes that
position easier to evaluate: the repo now shows what the agent can and cannot do, how regressions are
caught, and which claims are backed by runnable artifacts.

## Validation

Baseline after Phase 2:

- `pytest tests/ -q` -> 244 passed, 42 warnings.
- `pytest tests/test_eval_runner.py tests/test_eval_service.py tests/test_eval.py -q` -> 22 passed.
- `ruff check app/ tests/ scripts/ eval/` -> passed.
- `ruff format --check app/ tests/ scripts/ eval/` -> passed.
- `LLM_MODE=demo python -m eval.runner --gate --no-write` -> gate passed.

## Test Delta

The full baseline moved from 243 passing tests before T10 to 244 passing tests after T10. The eval
hardening work also added targeted tests for taxonomy coverage, structured metric serialization,
fail-closed output validation, seeded unsafe-regression detection, and CLI gate exit behavior.

## Open Findings

| ID | Severity | Risk | Status |
|----|----------|------|--------|
| ARCH-HARDEN-1 | P2 | `docs/ARCHITECTURE.md` still summarizes the older 25-case/basic-metric eval shape, so a reviewer who starts there may see stale eval detail before reaching `docs/EVALUATION.md` or `docs/EVAL_REPORT.md`. | Open, non-blocking doc patch |

There are no P0 or P1 findings from the Phase 2 deep review.

## Health Verdict

Health: green for continuing into Phase 3. Evaluation proof is stronger, CI has a deterministic
regression gate, and the only open finding is documentation drift outside the task-critical path.

## Next Phase

Phase 3 is Reliability And Failure-Mode Proof. The next task is T11, which creates the canonical
failure-mode taxonomy and SLO/runbook notes before adding scenario tests for replay, guard failures,
dependency degradation, and cross-tenant approval attempts.

