# gdev-agent Portfolio Review Guide

This guide is for a fast technical review of `gdev-agent` as a pilot-grade,
local portfolio system. It focuses on evidence that is committed in the repo
and avoids process history unless it explains proof quality.

## 5-minute path

1. Read the opening status and [Evidence Path](../README.md#evidence-path) in
   the README.
2. Scan [docs/EVIDENCE_INDEX.md](EVIDENCE_INDEX.md) for the claim, proof,
   verification, and gap table.
3. Check [Known Limits](../README.md#known-limits) before interpreting any
   architecture, eval, load, or demo claim.

## 15-minute path

1. Architecture: read [docs/ARCHITECTURE.md](ARCHITECTURE.md) sections 1-3 for
   the request flow, service boundaries, and local stack.
2. Demo: read [docs/DEMO.md](DEMO.md) to see the local approval workflow and
   prerequisites.
3. Eval: read [docs/EVALUATION.md](EVALUATION.md) and inspect
   [eval/cases.jsonl](../eval/cases.jsonl) for the current synthetic dataset.
4. Tenant isolation: read
   [docs/data-map.md#6-tenant-isolation-model](data-map.md#6-tenant-isolation-model)
   and [docs/ARCHITECTURE.md#7-security-model](ARCHITECTURE.md#7-security-model).
5. Observability and load: read [docs/observability.md](observability.md) for
   metrics/traces/logs and [docs/load-profile.md](load-profile.md) for local
   load assumptions.
6. Failure behavior and runbook status: read
   [docs/ARCHITECTURE.md#65-n8n-retry-strategy](ARCHITECTURE.md#65-n8n-retry-strategy),
   [docs/ARCHITECTURE.md#113-failure-modes-at-the-boundary](ARCHITECTURE.md#113-failure-modes-at-the-boundary),
   and [Known Limits](../README.md#known-limits).

## Technical deep-dive path

1. Control boundaries: inspect request ingress, signature/rate limit,
   guardrails, approval, audit, and cost paths in [docs/ARCHITECTURE.md](ARCHITECTURE.md).
2. Tenant isolation proof: run or inspect `tests/test_isolation.py`,
   `tests/test_rbac.py`, `tests/test_auth_service.py`,
   `tests/test_secrets_store.py`, and `tests/test_cost_ledger.py`.
3. Eval proof: run or inspect `tests/test_eval_runner.py`,
   `tests/test_eval.py`, and `eval/runner.py`.
4. Demo proof: run or inspect `scripts/demo.py`, `scripts/demo.sh`, and
   [docs/DEMO.md](DEMO.md).
5. Load and observability proof: inspect `load_tests/`, `tests/test_metrics.py`,
   `tests/test_observability.py`, [docs/load-profile.md](load-profile.md), and
   [docs/observability.md](observability.md).
6. Final known limits: use [README.md#known-limits](../README.md#known-limits)
   and [docs/tasks.md](tasks.md) to separate implemented evidence from planned
   hardening work.

## Do not infer

- No production SaaS readiness is claimed.
- No external deployment or live tenant traffic is claimed.
- Current demo, eval, and load evidence is local/synthetic unless a later
  report says otherwise.
