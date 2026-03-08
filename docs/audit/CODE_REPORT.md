---
# CODE_REPORT — Cycle 7
_Date: 2026-03-08 · Reviewer: PROMPT_2_CODE (senior security engineer)_

---

## Checklist Summary

| Check | Result | Notes |
|-------|--------|-------|
| SEC-1 SQL parameterization | PASS | Scoped SQL uses bound params; no f-string/concat SQL in `text()`/`execute()` |
| SEC-2 Tenant isolation | FAIL | Redis hot-path keys remain non-tenant-prefixed in dedup/approval/rate-limit modules |
| SEC-3 PII in logs | PASS | Scoped `LOGGER.*(... extra=...)` paths avoid raw `email`/`user_id`/`tenant_id` |
| SEC-4 Secrets scan | PASS | `git grep -rn "sk-ant\|lin_api_\|AKIA\|Bearer " app/` returned no matches |
| SEC-5 Async correctness | FAIL | Async RCA flow still performs sync Anthropic I/O via `summarize_cluster()` |
| SEC-6 Auth/RBAC | FAIL | `GET /metrics` remains JWT-exempt and has no `require_role()` policy dependency |
| QUAL-1 Error handling | FAIL | `_fetch_embeddings` still has broad fallback `except Exception` without warning log |
| QUAL-2 Observability | PARTIAL | Prometheus metrics exist; RCA background flow still lacks OTel span hierarchy |
| QUAL-3 Test coverage | PARTIAL | RCA fallback exception path still lacks direct unit coverage |
| CF carry-forward | Mixed | Several Cycle 6/Cycle 7 findings remain open and unchanged |

---

## Findings

### CODE-11 [P2] — Redis Hot-Path Keys Still Not Tenant-Namespaced
Symptom: Dedup/approval/rate-limit Redis keys are built without `{tenant}` prefix.
Evidence: `app/dedup.py:17`, `app/approval_store.py:25`, `app/middleware/rate_limit.py:95`
Root cause: Key schema implementation diverges from tenant-prefixed data-map contract.
Impact: Cross-tenant key collision risk and weaker isolation guarantees in shared Redis.
Fix: Prefix all per-tenant keys with tenant identity (or hashed stable tenant key) and migrate readers/writers atomically.
Verify: Add tests asserting key patterns include tenant prefix for dedup, pending, and rate-limit paths.
Confidence: high

### CODE-5 [P2] — ANN Fallback Still Uses Silent `except Exception`
Symptom: `_fetch_embeddings` catches broad `Exception` and silently falls back to date-order query.
Evidence: `app/jobs/rca_clusterer.py:228`
Root cause: Fallback path handles query failure but omits required warning context with traceback.
Impact: ANN degradation is invisible in logs; operators cannot distinguish healthy ANN mode from fallback mode.
Fix: Add `LOGGER.warning(..., exc_info=True)` before fallback query with safe `tenant_id_hash` context.
Verify: Force first query failure in test and assert fallback warning log with traceback is emitted.
Confidence: high

### CODE-9 [P2] — Blocking LLM I/O Inside Async RCA Path
Symptom: Async `_upsert_cluster` calls sync `LLMClient.summarize_cluster()`, which issues sync network I/O.
Evidence: `app/jobs/rca_clusterer.py:297`, `app/llm_client.py:274`, `app/llm_client.py:359`
Root cause: RCA background coroutine reused synchronous LLM client method without offloading.
Impact: Event-loop blocking can delay scheduler jobs and degrade async responsiveness under RCA load.
Fix: Use async transport or offload summarize call with `await asyncio.to_thread(...)` + timeout.
Verify: Add async concurrency test ensuring event loop remains responsive during summarize.
Confidence: high

### CODE-10 [P2] — `/metrics` Route Missing Explicit RBAC Contract Enforcement
Symptom: `/metrics` handler has no `require_role()` and middleware exempts it from JWT.
Evidence: `app/main.py:362`, `app/middleware/auth.py:54`
Root cause: Metrics endpoint shipped as public scrape target without explicit T07 exemption contract closure.
Impact: Operational telemetry may be unintentionally exposed on the app port.
Fix: Either enforce auth/RBAC on `/metrics` or codify explicit exemption + network boundary requirement and tests.
Verify: Add auth policy tests for `/metrics` that match chosen contract.
Confidence: high

### CODE-12 [P2] — Import-Time Settings Gate Can Break Runtime/Test Initialization
Symptom: `get_settings()` is executed at module import and raises if `ANTHROPIC_API_KEY` is absent.
Evidence: `app/main.py:223`, `app/config.py:97`, `tests/conftest.py:14`
Root cause: Middleware settings are bound at import-time rather than in startup/dependency path.
Impact: Import side effects create brittle startup/test behavior and hidden environment coupling.
Fix: Defer settings fetch to app factory/lifespan and avoid mandatory secret enforcement at import.
Verify: Import `app.main` in a clean env fixture without preset API key; module import should not raise.
Confidence: high

### CODE-8 [P3] — RCA Fallback Exception Branch Still Not Directly Tested
Symptom: No unit test drives `_fetch_embeddings` primary-query failure path through fallback SQL branch.
Evidence: `tests/test_rca_clusterer.py:1`
Root cause: Existing RCA tests cover cap/upsert/timeout and cross-tenant check but not ANN fallback branch.
Impact: Fallback regression risk remains undetected until runtime ANN/operator failures.
Fix: Add targeted unit test with first execute raising and second execute returning fallback rows.
Verify: Coverage includes `app/jobs/rca_clusterer.py:228-251`.
Confidence: high

---

## Carry-Forward Findings

| ID | Sev | Status | Evidence |
|----|-----|--------|----------|
| ARCH-1 | P1 | Open (unchanged) | HS256 runtime persists, no JWKS endpoint: `app/config.py:49`, `app/routers/auth.py:94`, `app/middleware/auth.py:75` |
| CODE-5 | P2 | Open (unchanged) | Silent broad fallback exception remains: `app/jobs/rca_clusterer.py:228` |
| CODE-9 | P2 | Open (unchanged) | Sync summarize in async RCA flow remains: `app/jobs/rca_clusterer.py:297`, `app/llm_client.py:274` |
| CODE-10 | P2 | Open (unchanged) | `/metrics` remains unauthenticated/JWT-exempt: `app/main.py:362`, `app/middleware/auth.py:54` |
| ARCH-2 | P2 | Open (unchanged) | Runtime still Voyage/1024 while ADR drift remains: `app/config.py:29` |
| ARCH-3 | P2 | Open (unchanged) | RCA Prometheus present; OTel span topology still incomplete: `app/jobs/rca_clusterer.py:109`, `app/jobs/rca_clusterer.py:130` |
| ARCH-4 | P2 | Open (unchanged) | RCA summarize path still bypasses CostLedger guard/accounting: `app/jobs/rca_clusterer.py:297`, `app/agent.py:678` |
| ARCH-6 | P2 | Open (unchanged) | Cluster detail still uses time-window heuristic membership: `app/routers/clusters.py:151` |
| ARCH-7 | P2 | Open (unchanged) | Service module still imports FastAPI HTTP exception: `app/agent.py:15` |
| P2-1 | P2 | Open (unchanged) | Redis keys not tenant-prefixed in hot paths: `app/dedup.py:17`, `app/approval_store.py:25`, `app/middleware/rate_limit.py:95` |
| P2-9 | P2 | Open (moved) | `_run_blocking()` duplication remains but now across modules: `app/agent.py:655`, `app/store.py:83` |
| P2-10 | P2 | Open (unchanged) | Import-time settings/API-key coupling remains: `app/main.py:223`, `app/config.py:97`, `tests/conftest.py:14` |
| CODE-8 | P3 | Open (unchanged) | Fallback branch still lacks direct unit test coverage |
| ARCH-5 | P3 | Open (unchanged) | RCA timeout remains 300s without ADR rationale closure: `app/jobs/rca_clusterer.py:107` |

---

CODE review done. P0: 0, P1: 0, P2: 5, P3: 1. Run PROMPT_3_CONSOLIDATED.md.
