# Tenant Isolation Boundary Proof

This document summarizes the local tenant-isolation evidence for the portfolio hardening track. It
is scoped to repository tests and local Postgres/Redis behavior; it does not claim external
production readiness.

## Boundary Contract

| Boundary | Expected behavior | Proof |
|----------|-------------------|-------|
| Postgres RLS reads | A tenant context can only read rows for its own tenant. | `tests/test_isolation.py::test_rls_filters_cross_tenant_reads` |
| Postgres RLS writes | A tenant context cannot insert rows for another tenant. | `tests/test_isolation.py::test_rls_blocks_cross_tenant_insert` |
| Pipeline persistence | Ticket, classification, extraction, proposed action, and audit rows are written for the payload tenant only. | `tests/test_isolation.py::test_event_store_binds_all_rows_to_payload_tenant` |
| Redis approval keys | Pending approvals are looked up by `{tenant_id}:pending:{pending_id}` and cross-tenant lookup misses. | `tests/test_approval_flow.py`, `tests/test_redis_approval_store.py`, `tests/test_isolation.py::test_approve_cross_tenant_is_forbidden_and_pending_remains` |
| Approval execution | Cross-tenant approval attempts are rejected before `execute_action()` and leave the original pending action intact. | `tests/test_approval_flow.py::test_cross_tenant_approval_does_not_execute_action`, `tests/test_isolation.py::test_approve_cross_tenant_is_forbidden_and_pending_remains` |
| Budget accounting | Budget checks are tenant-scoped before LLM calls and block spend at the tenant budget. | `tests/test_cost_ledger.py::test_budget_exhausted_returns_429_before_llm_call`, `tests/test_cost_ledger.py::test_check_budget_isolated_per_tenant` |
| Rate limiting | Webhook rate limits are keyed by tenant and user, and HTTP 429 stops downstream processing. | `tests/test_middleware.py::test_rate_limit_exceeded_for_same_user`, `tests/test_middleware.py::test_rate_limits_are_independent_per_user` |

## Failure Taxonomy Links

- `FM_CROSS_TENANT_APPROVAL` covers approval attempts using a tenant context that does not own the
  pending decision.
- `FM_APPROVAL_TTL_EXPIRED` covers stale approval tokens.
- `FM_RATE_LIMIT_EXCEEDED` covers bounded 429 behavior before downstream model or action work.
- `FM_BUDGET_EXCEEDED` covers budget blocks before LLM spend.

See [FAILURE_MODES.md](FAILURE_MODES.md) for the complete runbook taxonomy and
[SLO_RUNBOOK.md](SLO_RUNBOOK.md) for local operational targets.

## Current Limits

- The proof is local and test-backed. External deployment controls, production Redis ACLs, and
  tenant-facing dashboards are later deployment-readiness work.
- Some integration tests require Docker or `TEST_DATABASE_URL`. When unavailable, pytest records
  explicit skips rather than silently treating external infrastructure as present.

