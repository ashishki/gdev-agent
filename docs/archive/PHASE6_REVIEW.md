---
# REVIEW_REPORT — Cycle 6
_Date: 2026-03-08 · Scope: T16 observability + middleware/auth drift + carry-forward verification_

## Executive Summary
- Stop-Ship: No
- No P0 findings in current cycle.
- One P1 carry-forward remains: ADR-003 requires RS256, implementation remains HS256 with no JWKS endpoint.
- Cycle 6 closed prior code findings CODE-3, CODE-4, CODE-6, CODE-7 with direct code/test verification.
- New P2 findings from code review: blocking sync LLM call inside async RCA path (CODE-9), unauthenticated `/metrics` policy drift (CODE-10), and ANN fallback logging gap persists (CODE-5).
- Architecture drift remains concentrated in docs/contracts: ADR-002 (embedding model), webhook auth/signature spec mismatch, ADR-005 timeout rationale.
- Baseline unchanged: 111 pass, 12 skip.
- Phase 5 can continue (T16→T18), but auth architecture decision (ARCH-1) must be resolved before auth-phase changes.

## P0 Issues
None.

## P1 Issues
### ARCH-1 — ADR-003 RS256 Requirement Still Open
Symptom: JWT stack still uses HS256 and does not expose JWKS.
Evidence (file:line): `app/config.py:49`, `app/middleware/auth.py:74`, `app/routers/auth.py:94`, `docs/adr/003-rbac-design.md:53`
Root Cause: Earlier HS256 simplification was never reconciled with accepted ADR-003.
Impact: Security architecture is out of contract on key distribution/rotation; blocks clean IdP/public-key model adoption.
Fix: Architecture decision and implementation/doc alignment: either amend ADR-003 to HS256 constraints or implement RS256 + `/auth/jwks.json`.
Verify: Confirm selected design in ADR and verify code path/tests reflect it.

## P2 Issues
| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-5 | ANN fallback still catches broad exception without required warning + traceback context | `app/jobs/rca_clusterer.py:228` | Open |
| CODE-9 | Async RCA path calls sync `LLMClient.summarize_cluster()`; may block event loop | `app/jobs/rca_clusterer.py:297`, `app/llm_client.py:359` | Open |
| CODE-10 | `/metrics` route has no explicit RBAC/exemption contract update | `app/main.py:362` | Open |
| ARCH-2 | ADR-002 stale (OpenAI/1536) vs implementation (Voyage/1024) | `docs/adr/002-vector-database.md:32`, `app/config.py:29` | Open |
| ARCH-3 | RCA observability partial: metrics present, OTel background spans missing | `app/jobs/rca_clusterer.py:177`, `docs/observability.md:152` | Partial |
| ARCH-4 | RCA costs bypass CostLedger accounting per tenant | `app/jobs/rca_clusterer.py` | Open (deferred) |
| ARCH-5 | RCA timeout 300s diverges from ADR-005 120s example without clarification | `app/jobs/rca_clusterer.py:120`, `docs/adr/005-orchestration-model.md` | Open |
| ARCH-6 | `/clusters/{id}` returns ticket IDs by time-window heuristic, not true membership | `app/routers/clusters.py:151` | Open |
| ARCH-7 | Service-layer boundary violation: FastAPI `HTTPException` import in agent module | `app/agent.py:15` | Open |
| P2-1 | Redis keys in hot paths not tenant-namespaced | `app/dedup.py:17`, `app/approval_store.py:25`, `app/middleware/rate_limit.py:95` | Open (deferred) |
| P2-9 | `_run_blocking()` duplicated across modules | `app/agent.py`, `app/approval_store.py` | Open (deferred) |
| P2-10 | Module-level `get_settings()` path requires API key at import time | `app/main.py`, `tests/conftest.py` | Open |

## Carry-Forward Status
| ID | Sev | Description | Status | Change |
|----|-----|-------------|--------|--------|
| FIX-6 | P1 | Cross-tenant guard used `assert` | Closed | Verified prior cycle; remains closed |
| FIX-7 | P1 | RCA session blocks missing `SET LOCAL` | Closed | Verified prior cycle; remains closed |
| ARCH-1 | P1 | ADR-003 RS256 vs HS256 implementation | Open | No change |
| CODE-3 | P2 | Raw tenant UUID in logs | Closed | Verified fixed in `app/agent.py` |
| CODE-4 | P2 | `Bearer ` secrets-scan literal | Closed | Verified fixed in `app/embedding_service.py` |
| CODE-6 | P2 | Missing negative cross-tenant test | Closed | Verified in `tests/test_rca_clusterer.py:163` |
| CODE-7 | P2 | `tool_choice=auto` with `tools=[]` | Closed | Verified fixed in `app/llm_client.py:288-294` |
| CODE-5 | P2 | Silent ANN fallback exception | Open | No change |
| CODE-8 | P3 | No direct ANN fallback exception-path test | Open | No change |
| ARCH-2 | P2 | Vector ADR drift | Open | No change |
| ARCH-3 | P2 | RCA trace coverage incomplete | Partial | No change |
| ARCH-4 | P2 | CostLedger bypass in RCA | Open | No change |
| ARCH-5 | P3 | RCA timeout ADR mismatch | Open | No change |
| ARCH-6 | P2 | Cluster membership contract mismatch | Open | No change |
| ARCH-7 | P2 | Service/framework layer coupling | Open | Renamed from prior P2-6 wording |
| P2-1 | P2 | Redis tenant namespace drift | Open | No change |
| P2-9 | P2 | `_run_blocking()` duplication | Open | No change |
| P2-10 | P2 | Module import-time settings requirement | Open | No change |

## Stop-Ship Decision
No — no P0 findings and no new P1 blockers beyond known ARCH-1 architectural carry-forward. Phase 5 queue may proceed; auth-phase work remains gated on ARCH-1 resolution.
---
