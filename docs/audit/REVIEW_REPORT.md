---
# REVIEW_REPORT — Cycle 7
_Date: 2026-03-08 · Scope: Phase 5 targeted audit (auth contract + RCA/runtime drift)_

## Executive Summary
- Stop-Ship: No
- No P0 findings were identified in this cycle.
- One P1 architecture gate remains open: ADR-003 requires RS256+JWKS while runtime remains HS256 without JWKS.
- New code findings this cycle are P2/P3: Redis tenant key namespace drift (CODE-11), import-time settings coupling (CODE-12), and missing direct fallback-branch test (CODE-8).
- Prior P2 findings remain open: RCA async blocking risk (CODE-9), metrics policy drift (CODE-10), ANN fallback observability gap (CODE-5), and multiple architecture drift items.
- Baseline remains unchanged: 111 passing, 12 skipped, 0 failing.
- Phase 5 execution can continue; Phase 6 auth work remains gated on ARCH-1 closure.

## P0 Issues
None.

## P1 Issues
### ARCH-1 — RBAC Crypto Contract Unresolved (RS256/JWKS vs HS256)
Symptom: Runtime JWT signing/verification remains HS256 and no JWKS endpoint exists.
Evidence (file:line): `app/config.py:49`, `app/middleware/auth.py:75`, `app/routers/auth.py:94`, `docs/adr/003-rbac-design.md:53`
Root Cause: Security architecture decision was not closed after HS256 simplification.
Impact: Auth architecture gate remains open and blocks clean key-distribution/rotation posture.
Fix: Either implement RS256 + JWKS endpoint and tests, or formally amend ADR/gates to approved HS256 constraints.
Verify: Confirm accepted ADR state and verify runtime/tests match that state.

## P2 Issues
| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-11 | Redis hot-path keys are not tenant-namespaced | `app/dedup.py:17`, `app/approval_store.py:25`, `app/middleware/rate_limit.py:95` | Open |
| CODE-5 | ANN fallback catches broad exception without warning + traceback context | `app/jobs/rca_clusterer.py:228` | Open |
| CODE-9 | Async RCA path calls sync summarize I/O; risks event-loop blocking | `app/jobs/rca_clusterer.py:297`, `app/llm_client.py:274` | Open |
| CODE-10 | `/metrics` route has no explicit RBAC/exemption contract closure | `app/main.py:362`, `app/middleware/auth.py:54` | Open |
| CODE-12 | Import-time settings/API-key coupling can break startup/tests | `app/main.py:223`, `app/config.py:97`, `tests/conftest.py:14` | Open |
| ARCH-2 | ADR-002 vector stack drift (OpenAI/1536 docs vs Voyage/1024 runtime) | `docs/adr/002-vector-database.md:32`, `app/config.py:29` | Open |
| ARCH-3 | RCA cost path bypasses CostLedger budget/accounting | `app/jobs/rca_clusterer.py:297`, `app/agent.py:151` | Open |
| ARCH-4 | RCA observability topology lacks OTel background span hierarchy | `app/jobs/rca_clusterer.py:177`, `app/jobs/rca_clusterer.py:191` | Partial |
| ARCH-5 | `/metrics` exposure/auth contract drift vs spec assumptions | `app/main.py:362`, `docs/spec.md:91` | Open |
| ARCH-6 | Cluster details endpoint uses time-window heuristic, not persisted membership | `app/routers/clusters.py:151` | Open |
| ARCH-7 | Service-layer imports transport exception type (`HTTPException`) | `app/agent.py:15` | Open |
| ARCH-8 | Router layer still carries business logic that should be in services | `app/routers/auth.py:26`, `app/main.py:275` | Open |
| P2-9 | `_run_blocking()` helper duplication persists | `app/agent.py`, `app/store.py` | Open |
| P2-10 | Module-level settings path can require API key at import time | `app/main.py`, `tests/conftest.py` | Open |

## Carry-Forward Status
| ID | Sev | Description | Status | Change |
|----|-----|-------------|--------|--------|
| FIX-6 | P1 | Cross-tenant guard used `assert` | Closed | No change |
| FIX-7 | P1 | RCA session blocks missing `SET LOCAL` | Closed | No change |
| FIX-8 / ARCH-1 | P1 | ADR-003 RS256/JWKS vs HS256 runtime | Open | No change |
| CODE-3 | P2 | Raw tenant UUID in logs | Closed | No change |
| CODE-4 | P2 | Secrets-scan literal in app scope | Closed | No change |
| CODE-5 | P2 | Silent ANN fallback exception path | Open | No change |
| CODE-6 | P2 | Missing negative cross-tenant RCA test | Closed | No change |
| CODE-7 | P2 | `tool_choice` set with empty tools | Closed | No change |
| CODE-8 | P3 | ANN fallback exception branch lacks direct test | Open | No change |
| CODE-9 | P2 | Sync summarize in async RCA path | Open | No change |
| CODE-10 | P2 | `/metrics` auth/policy drift | Open | No change |
| CODE-11 | P2 | Redis keys not tenant-namespaced | Open | New this cycle |
| CODE-12 | P2 | Import-time settings/API-key coupling | Open | New this cycle |
| ARCH-2 | P2 | Vector ADR/runtime drift | Open | No change |
| ARCH-3 | P2 | RCA cost path bypasses CostLedger | Open | Refined scope |
| ARCH-4 | P2 | RCA OTel span hierarchy incomplete | Partial | No change |
| ARCH-5 | P2 | Metrics exposure contract drift | Open | Severity raised from prior P3 framing |
| ARCH-6 | P2 | Cluster membership semantics mismatch | Open | No change |
| ARCH-7 | P2 | Service/transport boundary violation | Open | No change |
| ARCH-8 | P2 | Router business-logic boundary violation | Open | New this cycle |
| P2-1 | P2 | Redis tenant namespace drift (legacy ID) | Open | Consolidated under CODE-11 |
| P2-9 | P2 | `_run_blocking()` duplication | Open | Module location updated |
| P2-10 | P2 | Import-time settings coupling | Open | No change |

## Stop-Ship Decision
No — no P0 findings and no new P1 blockers beyond known ARCH-1/FIX-8. Phase 5 work may continue; auth-phase queue remains gated by explicit ARCH-1 resolution.
---
