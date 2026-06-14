# REVIEW_REPORT — Cycle 17
_Date: 2026-06-14 · Scope: T18–T20_

## Executive Summary
- Stop-Ship: No.
- Phase 5 tenant isolation and security proof is complete enough to proceed toward Phase 6 after this review is archived.
- Orchestrator-verified baseline: `.venv/bin/python -m pytest tests/ -q` -> 272 passed, 0 skipped, 45 warnings.
- Tenant isolation proof, RLS/JWT boundaries, webhook HMAC boundary, approval boundary, tenant secret isolation, and tenant cost separation passed architecture review as local/test-backed controls.
- No P0 or P1 issues were identified by architecture review, code review, or consolidation.
- Five P2 issues remain open: logging consistency for broad catches, read-route service extraction, stale current-state docs, spec security-contract drift, and Phase 6 readiness documentation.
- One P3 load-profile caveat remains open: target/estimate language must stay clearly separated from measured local evidence.
- Next graph action is the Phase 6 T21 compose migration and health hardening work after archiving this review report.

## P0 Issues

None.

## P1 Issues

None.

## P2 Issues

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-1 | Broad `except Exception` handlers re-raise after spans or cleanup without required `LOGGER.error(..., exc_info=True)` logging. | `app/routers/clusters.py:161`, `app/routers/clusters.py:254`, `app/routers/clusters.py:367`, `app/approval_store.py:49` | Open |
| CODE-2 / ARCH-1 | Ticket, analytics, and cluster read APIs still embed SQL, pagination, metrics, error mapping, and response assembly in route handlers. | `app/routers/tickets.py:57`, `app/routers/analytics.py:58`, `app/routers/clusters.py:118` | Open |
| CODE-3 / ARCH-2 / ARCH-HARDEN-1 | Current-state docs still conflict with Cycle 17 evidence and security behavior, including stale test/eval counts and legacy webhook/approval semantics. | `docs/ARCHITECTURE.md:34`, `docs/ARCHITECTURE.md:73`, `README.md:3`, `README.md:241`, `docs/ARCHITECTURE.md:424`, `docs/ARCHITECTURE.md:597`, `docs/ARCHITECTURE.md:830` | Open |
| ARCH-3 | Product spec auth and production-secret assumptions lag the current architecture: protected REST APIs use JWT, while `/webhook` is JWT-exempt and tenant-resolved by signed slug plus per-tenant HMAC. | `docs/spec.md:91`, `docs/spec.md:100`, `docs/spec.md:181`, `docs/data-map.md:234` | Open |
| ARCH-4 | Phase 6 deployment-readiness architecture is not yet documented for compose migration checks, readiness/liveness behavior, secrets, backup/restore, production-like config, and known non-production boundaries. | `docs/audit/META_ANALYSIS.md:21`, `docs/ARCHITECTURE.md:483`, `README.md:224` | Open |

## Carry-Forward Status

| ID | Sev | Description | Status | Change |
|----|-----|-------------|--------|--------|
| ARCH-HARDEN-1 | P2 | Architecture eval summary referenced the old 25-case/basic metric shape after T07-T10. | Open | Consolidated into CODE-3 / ARCH-2 because the stale architecture snapshot now includes eval, evidence, baseline, and security-contract drift. |
| ARCH-1 | P2 | Read API business logic remains in route handlers for ticket, analytics, and cluster read APIs. | Open | Reconfirmed by architecture and code review; consolidated as CODE-2 / ARCH-1. |
| ARCH-2 | P2 | `docs/ARCHITECTURE.md` is stale relative to current evidence and security behavior. | Open | Expanded by Cycle 17 code review to include README, 272-test baseline, 180-case eval wording, tenant isolation proof, JWT approval, and per-tenant webhook HMAC. |
| CODE-1 (Cycle 16) | P2 | `docs/data-map.md` previously documented tenant RLS context as connection-level setup instead of transaction-local `SET LOCAL`. | Resolved/regression-check | Current data-map wording documents transaction-local `set_config(..., true)` inside `session.begin()`; not carried as an open Cycle 17 issue. |
| CODE-2 (Cycle 16) | P2 | README previously overstated service-layer separation while read routes still contained query/pagination/response logic. | Resolved/regression-check | README now limits service-layer claims, but the actual route extraction debt remains open as CODE-2 / ARCH-1. |
| CODE-4 / prior CODE-3 | P3 | `docs/load-profile.md` mixes scenario targets or estimates with measured local/synthetic evidence. | Open | Reconfirmed as non-blocking P3; clarify target-vs-measured boundaries during Phase 6 or final packaging. |
| ARCH-3 | P2 | `docs/spec.md` auth and production-secret assumptions lag current webhook/JWT architecture. | Open | New in Cycle 17 architecture review. |
| ARCH-4 | P2 | Phase 6 deployment-readiness architecture is not yet documented. | Open | New in Cycle 17 architecture review and aligned with planned T21/T22 work. |

## Stop-Ship Decision

No — there are no P0/P1 findings. The open issues are P2/P3 observability, architecture-boundary, and documentation-consistency items. CODE-1 should be fixed before relying on cluster and approval-store broad-catch diagnostics in incidents, while the remaining P2/P3 items can proceed through Phase 6 and final packaging.
