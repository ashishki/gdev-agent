---
# CODE_REPORT — Cycle 6
_Date: 2026-03-08 · Reviewer: PROMPT_2_CODE (senior security engineer)_

---

## Checklist Summary

| Check | Result | Notes |
|-------|--------|-------|
| SEC-1 SQL parameterization | PASS | Scoped SQL uses bound params (`:name`), no f-string SQL in scope files |
| SEC-2 Tenant isolation | PASS | Tenant-scoped RCA/embedding/agent DB paths set `SET LOCAL app.current_tenant_id` |
| SEC-3 PII in logs | PASS | No raw `tenant_id`/`email`/`user_id` in `LOGGER.*(... extra=...)` in scope |
| SEC-4 Secrets scan | PASS | `git grep -rn "sk-ant\|lin_api_\|AKIA\|Bearer " app/` returned no matches |
| SEC-5 Async correctness | FAIL | Blocking sync I/O remains inside async paths (RCA summarize call) |
| SEC-6 Auth/RBAC | FAIL | New `GET /metrics` handler has no `require_role()` and is not in T07 exemption matrix |
| QUAL-1 Error handling | FAIL | `_fetch_embeddings` has silent `except Exception` fallback without required logging |
| QUAL-2 Observability | PARTIAL | Prometheus is present; RCA background job still lacks OTel root spans |
| QUAL-3 Test coverage | PARTIAL | Cross-tenant negative test added; ANN fallback branch still lacks direct test coverage |
| CF carry-forward | Mixed | CODE-3/4/6/7 closed; CODE-5/8 and ARCH-6 remain open |

---

## Findings

### CODE-5 [P2] — ANN Fallback Still Uses Silent `except Exception`
Symptom: `_fetch_embeddings` catches broad `Exception` and falls back to date-order query without logging fallback activation/error context.
Evidence: `app/jobs/rca_clusterer.py:228`
Root cause: Fallback path handles query failures but omits required warning with `exc_info=True`.
Impact: ANN/index/operator failures are invisible in logs; operators cannot distinguish healthy ANN mode from degraded fallback mode.
Fix: Add `LOGGER.warning(..., exc_info=True)` before fallback query with safe tenant context (`tenant_id_hash`) and explicit fallback event.
Verify: Force first query failure in test, assert warning log emitted with fallback event and traceback.
Confidence: high

### CODE-8 [P3] — `_fetch_embeddings` Fallback Branch Still Not Unit-Tested
Symptom: No test exercises the exception path in `_fetch_embeddings` that executes fallback SQL.
Evidence: `tests/test_rca_clusterer.py:1`
Root cause: Current RCA tests monkeypatch `_fetch_embeddings` or cover other flows, but do not inject failure on primary ANN query.
Impact: Regressions in fallback SQL can ship undetected and only appear in production under ANN failure conditions.
Fix: Add a unit test with session stub that raises on first `execute` and succeeds on second, then assert fallback rows are returned.
Verify: Coverage includes `app/jobs/rca_clusterer.py:228-251`.
Confidence: high

### CODE-9 [P2] — Blocking LLM I/O Inside Async RCA Path
Symptom: Async `_upsert_cluster` calls sync `LLMClient.summarize_cluster()`, which uses sync Anthropic client call.
Evidence: `app/jobs/rca_clusterer.py:297`, `app/llm_client.py:359`
Root cause: RCA job is async, but summarize path reuses synchronous LLM transport without offloading.
Impact: Event loop can be blocked during cluster summarization; scheduler latency and concurrent async task responsiveness degrade.
Fix: Move summarize call to async transport (preferred) or offload with `await asyncio.to_thread(...)` and instrument timeout/retries explicitly.
Verify: Add async test that runs concurrent task during summarize and confirms loop is not blocked beyond expected threshold.
Confidence: high

### CODE-10 [P2] — `/metrics` Route Missing RBAC Dependency
Symptom: Newly added `GET /metrics` handler has no `require_role()` dependency.
Evidence: `app/main.py:362`
Root cause: Prometheus scrape endpoint was added as unauthenticated route without explicit exemption update in T07 role matrix.
Impact: Internal operational metrics become publicly accessible on app port unless external network policy strictly blocks access.
Fix: Either enforce role/JWT on `/metrics`, or document and codify explicit exemption with infrastructure boundary requirements (private network only).
Verify: RBAC test asserts unauthenticated `/metrics` behavior matches decided policy.
Confidence: medium

---

## Carry-Forward Findings

| ID | Sev | Status | Evidence |
|----|-----|--------|----------|
| CODE-3 | P2 | Closed | `app/agent.py` now uses `tenant_id_hash` in logger contexts; raw tenant UUID log extras removed |
| CODE-4 | P2 | Closed | Secrets scan now clean (`Bearer ` literal no longer matched in `app/`) |
| CODE-5 | P2 | Open | `app/jobs/rca_clusterer.py:228` silent broad exception remains |
| CODE-6 | P2 | Closed | Negative cross-tenant test present: `tests/test_rca_clusterer.py:163` |
| CODE-7 | P2 | Closed | `summarize_cluster()` no longer sends `tool_choice` with empty tools: `app/llm_client.py:288-294` |
| CODE-8 | P3 | Open | Fallback branch still lacks direct unit coverage |
| ARCH-6 | P2 | Open | Cluster detail still uses time-window heuristic, not persisted membership: `app/routers/clusters.py:151-177` |

---

CODE review done. P0: 0, P1: 0, P2: 3, P3: 1. Run PROMPT_3_CONSOLIDATED.md.
