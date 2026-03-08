---
# REVIEW_REPORT — Cycle 4
_Date: 2026-03-08 · Scope: T13–T15_

## Executive Summary

- **Stop-Ship: No** — No P0 findings; two P1 findings must be resolved before Phase 5 ships.
- Phase 4 (T13–T15) implemented: EmbeddingService, RCAClusterer background job, Cluster API endpoints, Migration 0004.
- Baseline unchanged: 111 pass, 12 skip. No regressions against prior baseline.
- **Critical (FIX-6):** RCAClusterer cross-tenant guard uses Python `assert` — silently disabled under `-O` flag; complete raw_text PII leak path in optimized builds.
- **Critical (FIX-7):** Three RCAClusterer session blocks missing `SET LOCAL` — job is silent no-op in production (RLS blocks all queries from `gdev_app`).
- Architecture gap: RCA budget approximation bypasses `CostLedger`; tenant daily budgets not decremented for RCA LLM costs.
- ADR-002 stale: documents OpenAI `text-embedding-3-small` / VECTOR(1536); actual implementation uses Voyage AI `voyage-3-lite` / VECTOR(1024).
- P1-1 (RS256 decision) carries forward — must be resolved before Phase 5 if auth is modified.

---

## P0 Issues

_None._

---

## P1 Issues

### P1-1 — ADR-003 Mandates RS256; HS256 Still Implemented _(carry-forward from Cycle 1)_

**Symptom:** JWT signing algorithm is HS256 (symmetric). No JWKS endpoint exists.
**Evidence:** `app/config.py:49` — `jwt_algorithm: str = "HS256"`; `docs/adr/003-rbac-design.md` §Decision — "JWT signed with RS256. Public key published at `/auth/jwks.json`."
**Root Cause:** HS256 shipped as v1 simplification; no ADR amendment made.
**Impact:** No key rotation without downtime; no JWKS discovery; blocks external IdP migration path.
**Fix:** Architecture decision required before Phase 5 touches auth. Options: (a) accept HS256 + amend ADR-003; (b) implement RS256 + JWKS endpoint.
**Verify:** New or amended ADR recorded; implementation matches decision.

---

### FIX-6 [P1] — `assert` Used as Cross-Tenant Security Boundary in Production Code

**Symptom:** `_fetch_raw_texts_admin` guards cross-tenant isolation with `assert cluster_tenant_id == tenant_id`. Python optimizations (`-O` / `PYTHONOPTIMIZE=1`) silently disable all assertions.
**Evidence:** `app/jobs/rca_clusterer.py:382-383`
```python
cluster_tenant_id = str(row["tenant_id"])
assert cluster_tenant_id == tenant_id
```
`gdev_admin` bypasses RLS; this assertion is the only cross-tenant safeguard after bypass.
**Root Cause:** `assert` used instead of an explicit conditional check.
**Impact:** If a container image is built or run with `-O` (common in distroless/production Python configs), cross-tenant raw ticket text is returned without any error or log. Complete cross-tenant PII leak for `raw_text`.
**Fix:** Replace with:
```python
if cluster_tenant_id != tenant_id:
    LOGGER.error("cross-tenant row detected", extra={"context": {"tenant_id_hash": _sha256_short(tenant_id)}})
    raise ValueError(f"Cross-tenant isolation breach: got {cluster_tenant_id}, expected {tenant_id}")
```
**Verify:** Negative unit test — admin stub returns row with mismatched `tenant_id`; call raises `ValueError`. Confirm guard fires under `python -O`.

---

### FIX-7 [P1] — RCAClusterer Session Blocks Missing `SET LOCAL app.current_tenant_id`

**Symptom:** `_fetch_embeddings`, `_deactivate_existing_clusters`, and cluster write in `_upsert_cluster` open sessions without `SET LOCAL app.current_tenant_id`. RLS on `ticket_embeddings` and `cluster_summaries` blocks all `gdev_app` queries without this setting.
**Evidence:**
- `app/jobs/rca_clusterer.py:212` — `_fetch_embeddings` session; no `SET LOCAL` before SELECT
- `app/jobs/rca_clusterer.py:258` — `_deactivate_existing_clusters` session; no `SET LOCAL` before UPDATE
- `app/jobs/rca_clusterer.py:314` — `_upsert_cluster` write session; no `SET LOCAL` before INSERT

dev-standards §3.6 requires `SET LOCAL` before all tenant-scoped queries.
**Root Cause:** Background job uses `_db_session_factory` directly instead of `get_db_session` (which calls `SET LOCAL`). All unit tests use stub sessions that bypass RLS — no test catches this.
**Impact:** RCA clustering job is silently a no-op in production. `_fetch_embeddings` returns zero rows, `run_tenant` exits early, no clusters are written.
**Fix:** Add `await session.execute(text("SET LOCAL app.current_tenant_id = :tid"), {"tid": tenant_id})` at the start of each session block in all three locations.
**Verify:** Integration test with real Postgres + RLS policies: `run_tenant(tenant_id)` produces cluster rows in `cluster_summaries`.

---

## P2 Issues

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-3 | Raw `tenant_id` UUID in log extra — violates dev-standards §3.5; must use `sha256(str(tenant_id))[:16]` | `app/agent.py:578,602` | Open — new |
| CODE-4 | `Bearer ` literal fails mandatory secrets scan (`git grep -rn "Bearer " app/` must return empty) | `app/embedding_service.py:146` | Open — new |
| CODE-5 | Silent bare `except Exception` without `LOGGER.warning(..., exc_info=True)` in ANN fallback path | `app/jobs/rca_clusterer.py:236` | Open — new |
| CODE-6 | Cross-tenant isolation guard (FIX-6 target) has no negative unit test | `tests/test_rca_clusterer.py` | Open — fix after FIX-6 |
| CODE-7 | `summarize_cluster()` passes `tool_choice={"type":"auto"}` with `tools=[]` — invalid combination may cause API 400 | `app/llm_client.py:252-259` | Open — new |
| ARCH-2 | ADR-002 stale: documents `text-embedding-3-small` / VECTOR(1536) / OpenAI; actual: `voyage-3-lite` / VECTOR(1024) / Voyage AI | `docs/adr/002-vector-database.md` | Open — doc fix only |
| ARCH-3 | RCAClusterer emits Prometheus metrics but no OTel trace spans — ADR-004 §Instrumentation Scope violated | `app/jobs/rca_clusterer.py` | Open — new |
| ARCH-4 | RCAClusterer budget approximation (cluster count cap) bypasses `CostLedger`; RCA LLM costs not recorded against tenant daily budget | `app/jobs/rca_clusterer.py:164-180` | Open — new |
| ARCH-6 | `GET /clusters/{id}` ticket_ids returned by timestamp heuristic, not actual cluster membership — misleading API contract | `app/routers/clusters.py:152-175` | Open — new |
| P2-1 | Redis keys not tenant-namespaced (doc vs code drift in `data-map.md §3`) | `app/dedup.py`, `app/approval_store.py` | Open — deferred Phase 5 |
| P2-6 | `app/agent.py:15` imports `HTTPException` from fastapi (service layer violation) | `app/agent.py` | Open — deferred |
| P2-9 | `_run_blocking()` duplicated in `app/agent.py` and `app/approval_store.py` | `app/agent.py:495`, `app/approval_store.py` | Open — deferred |
| P2-10 | `get_settings()` at module level (`app/main.py:179`) requires `ANTHROPIC_API_KEY` at import time | `app/main.py`, `tests/conftest.py` | Open — documented |

---

## P3 Issues

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-8 | `_fetch_embeddings` ANN fallback path (lines 238–254) has no unit test; exception injection not tested | `app/jobs/rca_clusterer.py`, `tests/test_rca_clusterer.py` | Open — new |
| ARCH-5 | RCA job timeout 300 s vs ADR-005 example 120 s; multi-tenant pathology risk not documented | `app/jobs/rca_clusterer.py:120`, `docs/adr/005-orchestration-model.md` | Open — doc clarification needed |

---

## Carry-Forward Status

| ID | Sev | Description | Status | Change |
|----|-----|-------------|--------|--------|
| P1-1 | P1 | ADR-003 mandates RS256; HS256 implemented | Open — architecture decision required | No change |
| P2-1 | P2 | Redis keys not tenant-namespaced | Open — deferred Phase 5 | No change |
| P2-6 | P2 | `agent.py` imports `HTTPException` from fastapi | Open — deferred | No change |
| P2-9 | P2 | `_run_blocking()` duplicated | Open — deferred | No change |
| P2-10 | P2 | `get_settings()` at module level | Open — documented | No change |

No carry-forward finding worsened this cycle.

---

## Stop-Ship Decision

**No.** No P0 findings. Two P1 findings (FIX-6, FIX-7) are isolated to `app/jobs/rca_clusterer.py` and affect only the background RCA job — existing `/webhook`, `/approve`, and API paths are unaffected. Both must be resolved before Phase 5 ships.

Next: archive this file to `docs/archive/PHASE4_REVIEW.md` before Cycle 5.
---
