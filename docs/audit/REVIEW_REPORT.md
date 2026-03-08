---
# REVIEW_REPORT — Cycle 5
_Date: 2026-03-08 · Scope: FIX-6, FIX-7 verification + carry-forward audit (no new phase shipped)_

## Executive Summary

- **Stop-Ship: No** — FIX-6 and FIX-7 verified resolved; Phase 5 gate cleared. No P0 findings.
- FIX-6 (assert → ValueError cross-tenant guard) confirmed fixed: `app/jobs/rca_clusterer.py:400–411` — `raise ValueError(...)` present, no `assert` statement.
- FIX-7 (SET LOCAL missing in session blocks) confirmed fixed: SET LOCAL present in all four session contexts (`_fetch_embeddings` primary, `_fetch_embeddings` ANN fallback, `_deactivate_existing_clusters`, `_upsert_cluster`).
- `feat(metrics)` commit partially addressed ARCH-3: Prometheus metrics added to RCAClusterer; OTel root trace spans still absent (observability.md §3.2 not satisfied).
- Baseline unchanged: 111 pass, 12 skip. No regressions.
- P1-1 / ARCH-1 (RS256) carries forward (open since Cycle 1). T16–T18 are observability tasks; they do not touch auth paths — no current blocker for Phase 5.
- ARCH-6 (`GET /clusters/{id}` ticket_ids by timestamp heuristic) is not acceptable as a permanent contract; must be resolved before GA (schema migration or API contract amendment).

---

## P0 Issues

_None._

---

## P1 Issues

### ARCH-1 — ADR-003 Mandates RS256; HS256 Still Implemented _(carry-forward from Cycle 1)_

**Symptom:** JWT signing algorithm is HS256 (symmetric). No JWKS endpoint exists.
**Evidence:** `app/config.py:49` — `jwt_algorithm: str = "HS256"`; `docs/adr/003-rbac-design.md` §Decision — "JWT signed with RS256 (asymmetric). Public key published at `/auth/jwks.json`."
**Root Cause:** HS256 shipped as v1 simplification; ADR-003 never amended.
**Impact:** No key rotation without downtime; no JWKS discovery; blocks external IdP migration path in ADR-003 §Alternatives.
**Fix:** Architecture decision required. Options: (a) accept HS256 — amend ADR-003 with rationale; (b) implement RS256 + JWKS endpoint. Either path must be recorded in a new ADR or ADR-003 amendment.
**Verify:** New or amended ADR recorded; implementation matches decision.
**Phase 5 impact:** T16–T18 (observability) do not touch auth paths. No blocker for Phase 5. **Must** be resolved before Phase 6 if any task modifies `app/middleware/auth.py`, `app/config.py` JWT fields, or adds auth endpoints.

---

## P2 Issues

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-3 | Raw `tenant_id` UUID in log extra — violates dev-standards §3.5; must use `sha256(str(tenant_id))[:16]` | `app/agent.py:578,602` | Open — carry-forward |
| CODE-4 | `Bearer ` literal fails mandatory secrets scan (`git grep -rn "Bearer " app/` must return empty) | `app/embedding_service.py:146` | Open — carry-forward |
| CODE-5 | Silent bare `except Exception` without `LOGGER.warning(..., exc_info=True)` in ANN fallback path | `app/jobs/rca_clusterer.py:236` | Open — carry-forward |
| CODE-6 | Cross-tenant isolation guard (FIX-6) has no negative unit test | `tests/test_rca_clusterer.py` | Open — unblocked (FIX-6 resolved) |
| CODE-7 | `summarize_cluster()` passes `tool_choice={"type":"auto"}` with `tools=[]` — invalid combination may cause API 400 | `app/llm_client.py:252-259` | Open — carry-forward |
| ARCH-2 | ADR-002 stale: documents `text-embedding-3-small` / VECTOR(1536) / OpenAI; actual: `voyage-3-lite` / VECTOR(1024) / Voyage AI | `docs/adr/002-vector-database.md` | Open — doc fix only |
| ARCH-3 | RCAClusterer: Prometheus metrics added by `feat(metrics)` ✅; OTel root trace spans still absent — observability.md §3.2 violated | `app/jobs/rca_clusterer.py` | PARTIAL — Prometheus ✅, OTel traces ✗ |
| ARCH-4 | RCAClusterer budget approximation (cluster count cap) bypasses `CostLedger`; RCA LLM costs not recorded against tenant daily budget | `app/jobs/rca_clusterer.py:164-180` | Open — deferred (acceptable ≤10 tenants; fix before 5+ active) |
| ARCH-6 | `GET /clusters/{id}` ticket_ids returned by timestamp heuristic, not actual cluster membership — violates spec.md §8 | `app/routers/clusters.py:152-175` | Open — not acceptable as permanent contract; fix before GA |
| P2-1 | Redis keys not tenant-namespaced (doc vs code drift in `data-map.md §3`) | `app/dedup.py`, `app/approval_store.py` | Open — deferred Phase 5 |
| P2-6 | `app/agent.py:15` imports `HTTPException` from fastapi (service layer violation) | `app/agent.py` | Open — deferred |
| P2-9 | `_run_blocking()` duplicated in `app/agent.py` and `app/approval_store.py` | `app/agent.py:495`, `app/approval_store.py` | Open — deferred |
| P2-10 | `get_settings()` at module level (`app/main.py:179`) requires `ANTHROPIC_API_KEY` at import time | `app/main.py`, `tests/conftest.py` | Open — documented |

---

## P3 Issues

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-8 | `_fetch_embeddings` ANN fallback path (lines 238–254) has no unit test; exception injection not tested | `app/jobs/rca_clusterer.py`, `tests/test_rca_clusterer.py` | Open — carry-forward |
| ARCH-5 | RCA job timeout 300 s vs ADR-005 example 120 s; multi-tenant pathology risk not documented | `app/jobs/rca_clusterer.py:120`, `docs/adr/005-orchestration-model.md` | Open — doc clarification needed |

---

## Carry-Forward Status

| ID | Sev | Description | Status | Change |
|----|-----|-------------|--------|--------|
| FIX-6 | P1 | `assert` cross-tenant guard | **CLOSED** — `raise ValueError` verified at lines 400–411 | Closed Cycle 5 |
| FIX-7 | P1 | SET LOCAL missing in session blocks | **CLOSED** — SET LOCAL verified in all 4 session contexts | Closed Cycle 5 |
| ARCH-1 (P1-1) | P1 | ADR-003 mandates RS256; HS256 implemented | Open — architecture decision required | No change; T16–T18 don't touch auth |
| CODE-6 | P2 | No negative test for cross-tenant guard | Open — **unblocked** (FIX-6 resolved) | Unblocked this cycle |
| ARCH-3 | P2 | RCAClusterer OTel traces absent | PARTIAL — Prometheus ✅, OTel ✗ | Updated (was fully Open) |
| CODE-3 | P2 | Raw tenant_id in log extra | Open | No change |
| CODE-4 | P2 | `Bearer ` literal in embedding_service.py | Open | No change |
| CODE-5 | P2 | Silent bare except in ANN fallback | Open | No change |
| CODE-7 | P2 | tool_choice=auto with tools=[] | Open | No change |
| ARCH-2 | P2 | ADR-002 stale (doc fix) | Open | No change |
| ARCH-4 | P2 | CostLedger bypass in RCAClusterer | Open — deferred | No change |
| ARCH-6 | P2 | ticket_ids timestamp heuristic | Open — pre-GA fix required | No change |
| P2-1 | P2 | Redis keys not tenant-namespaced | Open — deferred | No change |
| P2-6 | P2 | fastapi import in agent.py | Open — deferred | No change |
| P2-9 | P2 | _run_blocking() duplicated | Open — deferred | No change |
| P2-10 | P2 | get_settings() at module level | Open — documented | No change |
| CODE-8 | P3 | ANN fallback path untested | Open | No change |
| ARCH-5 | P3 | Timeout 300 s undocumented | Open | No change |

---

## Stop-Ship Decision

**No.** FIX-6 and FIX-7 are resolved; Phase 5 gate cleared. ARCH-1 (P1, RS256) does not block T16–T18 (observability scope, no auth changes). No P0 findings. T16 may proceed.

Next: archive this file to `docs/archive/PHASE5_REVIEW.md` before Cycle 6.
---
