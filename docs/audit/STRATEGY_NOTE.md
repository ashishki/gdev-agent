# STRATEGY_NOTE — Phase 3
_Date: 2026-06-12_

## Platform Identity

Phase 3 strengthens the project identity as a governed AI support reliability system. The tasks
focus on replay behavior, guard failures, dependency degradation, approval expiry, budget/rate
limits, and tenant-boundary failures, which are directly aligned with the portfolio-hardening scope.

## Structural Drift Assessment

| Finding | Cycles open | Structural pattern | Action |
|---|---:|---|---|
| ARCH-HARDEN-1 | 1 | Documentation drift: architecture eval summary trails the implemented dataset and gate | Carry into doc patch; not blocking Phase 3 |
| Historical CODE-6 | 0 in rebuilt graph | Closed safety gap: direct `run_eval()` now budget-checks when an agent has a DB session and falls back to demo mode without live credentials | No action |

## ADR Alignment

| ADR | Conflict | Recommendation |
|---|---|---|
| ADR-001 Storage | Phase 3 depends on Postgres/RLS failure behavior already chosen by ADR-001 | Proceed |
| ADR-003 RBAC | T14 cross-tenant approval tests reinforce the accepted JWT/RLS design | Proceed |
| ADR-004 Observability | T11 should map failure modes to logs, metrics, and traces | Proceed |
| ADR-005 Orchestration | T13 provider/dependency degradation tests may clarify async job retry behavior but do not contradict ADR-005 | Proceed |

## Phase Risk

Highest-risk task: T14 — Approval Rate Budget And Tenant-Boundary Failure Tests

Required test: cross-tenant approval attempt is rejected before execution and cannot create
approved action/audit/cost side effects.

## Recommendation

Proceed

Phase 3 is aligned with the hardening plan. Start with T11 taxonomy/runbook so later scenario tests
can assert stable error names instead of inventing per-test strings.
