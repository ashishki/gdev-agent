# Phase Report - Portfolio Hardening Phase 4

Date: 2026-06-12

## What Was Built

Phase 4 added local load and observability evidence without turning the project into a production
capacity claim.

- T15 aligned the Locust harness around five bounded scenarios: 1-tenant low load, 10-tenant mixed
  load, duplicate replay, risky-action heavy traffic, and provider-latency simulation.
- T15 also added fixture safety checks so load-test messages reject real PII and secret-like
  values.
- T16 published `docs/LOAD_TEST_REPORT.md` plus committed deterministic result fixtures under
  `load_tests/results/local-deterministic-2026-06-12/`.
- T17 mapped workflow debugging signals from request ingress through guardrails, LLM calls,
  approval routing, execution, audit, budget, and failure-mode runbooks.
- T17 updated the Grafana dashboard JSON to remain tenant-safe and Prometheus-only, avoiding direct
  tenant table queries from dashboard panels.

## Why It Matters

The portfolio claim is now easier to inspect: a reviewer can see how load scenarios are configured,
which metrics matter, how KPI output is interpreted, and which dashboard panels answer concrete
debugging questions. The report is explicit that this is local deterministic/synthetic evidence, not
production throughput proof.

## Validation

Baseline after Phase 4:

- `.venv/bin/python -m pytest tests/ -q` -> 263 passed, 42 warnings.
- `.venv/bin/python -m pytest tests/test_load_test_fixtures.py -q` -> 8 passed.
- `.venv/bin/python -m pytest tests/test_observability.py tests/test_metrics.py -q` -> 8 passed.
- `.venv/bin/python load_tests/check_kpis.py --help` -> passed.
- `.venv/bin/python load_tests/check_kpis.py --dry-run` -> passed.
- `.venv/bin/ruff check app/ tests/ load_tests/` -> passed.
- `.venv/bin/ruff format --check app/ tests/ load_tests/` -> passed.

## Test Delta

The full baseline moved from 256 passing tests after Phase 3 to 263 passing tests after Phase 4.
New tests cover load profile coverage, fixture PII/secret rejection, KPI reporting, dashboard
signals, tenant-safe metric labels, and dashboard avoidance of direct Postgres tenant queries.

## Open Findings

| ID | Severity | Risk | Status |
|----|----------|------|--------|
| CODE-1 | P2 | `docs/data-map.md` describes tenant context as connection-level `SET` instead of transaction-local `SET LOCAL`, which is unsafe guidance for pooled connections. | Open; should be fixed during T18 |
| CODE-2 | P2 | README overstates full service-layer separation while read-route drift remains. | Open; soften claim or complete read-service extraction |
| ARCH-1 | P2 | Ticket, analytics, and cluster read APIs still contain read/query logic in routers. | Open; non-blocking for T18 |
| ARCH-2 / ARCH-HARDEN-1 | P2 | `docs/ARCHITECTURE.md` is stale relative to eval, audit, load, and observability evidence. | Open; doc refresh before final packaging |
| CODE-3 / ARCH-3 | P3 | `docs/load-profile.md` still mixes targets with unmeasured deterministic evidence. | Open; add caveats before final packaging |

There are no P0 or P1 findings from the Phase 4 deep review.

## Health Verdict

Health: green for continuing into Phase 5. Load and observability proof now has runnable local
commands, committed artifacts, tenant-safe dashboard checks, and no stop-ship findings. The open
items are claim-consistency and documentation-boundary issues, not runtime blockers.

## Next Phase

Phase 5 is Tenant Isolation And Security Proof. The next task is T18, which should make
`docs/TENANT_ISOLATION.md` the canonical reviewer entrypoint and address the `SET LOCAL` data-map
guidance as part of tenant-isolation documentation cleanup.
