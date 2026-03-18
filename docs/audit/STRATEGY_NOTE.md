# STRATEGY_NOTE — Phase 8
_Date: 2026-03-18_

---

## Platform Identity

Phase 8 is a pure technical-debt resolution phase (FIX-A through FIX-F): Redis namespacing, async correctness, OTel instrumentation, eval budget enforcement, utility deduplication, and a documentation comment. None of these tasks introduce new features or touch the triage pipeline directly. All six strengthen the platform's reliability and multi-tenant correctness, which are prerequisites for operating as a production "AI Support Intelligence Platform." There is no identity dilution risk.

---

## Structural Drift Assessment

| Finding | Cycles open | Structural pattern | Action |
|---|---|---|---|
| CODE-11 / P2-1 — Redis keys non-tenant-scoped | 3+ | Missing data isolation: shared Redis namespace allows cross-tenant key collisions in hot paths (dedup, approvals, rate-limit) | Must resolve — FIX-A scheduled |
| CODE-9 — Blocking `summarize_cluster` in async path | 3+ | Async correctness violation: sync blocking I/O in async coroutine risks event-loop stall under load; forbidden by IMPLEMENTATION_CONTRACT | Must resolve — FIX-C scheduled |
| ARCH-4 — Zero OTel spans in RCA Clusterer | 2+ (confirmed zero spans post-T14) | Observability gap: ADR-004 mandates spans per pipeline stage; background job is a black box to operators | Must resolve — FIX-D scheduled |
| ARCH-3 — Eval runner bypasses CostLedger budget check | 3+ | Safety gate violation: spec §5 rule #6 and IMPLEMENTATION_CONTRACT both mandate `check_budget()` before every LLM call; eval runner silently bypasses this | Must resolve — FIX-E scheduled |
| P2-9 — `_run_blocking` duplicated | 3+ | DRY / maintenance risk: divergence between copies will cause silent behavioral differences under future changes | Carry forward acceptable but FIX-B low-risk and removes drift vector |
| CODE-5 — Broad `except Exception` in `_fetch_embeddings` | 3+ | Silent failure masking: exception swallowed without structured error; forbidden by IMPLEMENTATION_CONTRACT | Not in Phase 8 scope — carry forward with explicit task in Phase 9 backlog |
| ARCH-7 — Layer violation `app/agent.py:15` imports `HTTPException` | 3+ | Layer violation: service layer importing from FastAPI HTTP layer couples agent logic to web framework | Not in Phase 8 scope — addressed by SVC-1/SVC-2 in Phase 9 |
| ARCH-8 — Business logic in router layer | 3+ | Layer violation: auth and eval routers contain business logic | Not in Phase 8 scope — addressed by Phase 9 service extraction |

**Structural verdict:** Two findings (CODE-9, ARCH-3) represent contract violations that must not persist beyond this phase. CODE-11 is a data-isolation gap that could cause cross-tenant data leakage in a shared Redis deployment. FIX-A, FIX-C, and FIX-E are therefore the highest-priority deliverables in Phase 8.

---

## ADR Alignment

| ADR | Conflict | Recommendation |
|---|---|---|
| ADR-003 (RBAC / JWT) | FIX-A adds `tenant_id` to the rate-limit Redis key, which requires `tenant_id` to be available in `RateLimitMiddleware`. The middleware currently reads `user_id` from the JWT. This is consistent with ADR-003 (tenant_id is a JWT claim). No conflict, but implementation must extract `tenant_id` from `request.state` (set by `JWTMiddleware`) — ensure ordering in middleware stack is preserved. | No ADR update needed; verify middleware stack ordering in `app/main.py` before implementing FIX-A. |
| ADR-004 (OTel + Prometheus) | FIX-D adds OTel spans to `rca_clusterer.py`. ADR-004 specifies `rca_clusterer.py` should emit `rca.run`, `rca.cluster`, and — after FIX-C lands — `rca.summarize`. The task spec matches ADR-004 span hierarchy exactly. No conflict. | No ADR update needed. FIX-D must be implemented after FIX-C (FIX-C renames the call site that FIX-D instruments). |
| ADR-002 (pgvector / embedding model) | ARCH-2 (open): `ticket_embeddings.embedding` is `VECTOR(1536)` per ADR-002 (OpenAI text-embedding-3-small) but the live `EmbeddingService` uses Voyage/1024. This dimension mismatch will cause silent failures or schema rejection at ingestion time. Phase 8 does not address ARCH-2, but it should be escalated — it is not blocked by Phase 8 tasks. | Accept drift for Phase 8. Add ADR-002 revision or a new ADR (ADR-006) as first item in Phase 9 backlog. |
| ADR-005 (APScheduler / async jobs) | FIX-C converts the sync `summarize_cluster` call to `asyncio.to_thread()`. ADR-005 requires background jobs to be `async def` coroutines running on the event loop with blocking DB via a thread pool. `asyncio.to_thread()` is the correct pattern. No conflict. | No ADR update needed. |

---

## Phase Risk

**Highest-risk task: FIX-A — Tenant-namespace Redis hot-path keys**

Risk factors:
1. Three files must be changed atomically. Any partial rollout (e.g., `dedup.py` updated but `approval_store.py` not) leaves inconsistent keys and will break the approval round-trip in production.
2. The `RateLimitMiddleware` key change requires `tenant_id` to be reliably present in `request.state` before the rate-limit middleware runs. If a request arrives without a decoded JWT (e.g., `/webhook` is exempt from JWT auth), `tenant_id` will be `None` — the key must fall back to a non-prefixed or `tenant:unknown` form without crashing.
3. Existing test fixtures that assert Redis key names will need to be updated in lock-step; missing any will produce false-green tests against stale key patterns.

**Required test:** `tests/test_rate_limit.py` and `tests/test_dedup.py` must include a case where `tenant_id=None` (unauthenticated/webhook path) — verify the middleware does not raise `KeyError` or produce a malformed key. Additionally, `tests/test_approval_store.py` must assert that `pop()` and `put()` use the same prefixed key and that a key written with one tenant_id is not retrievable with a different tenant_id (cross-tenant isolation regression test).

---

## Recommendation

**Proceed with modification.**

Implement FIX-A through FIX-F in the following adjusted order to manage dependencies:

1. **FIX-B first** (extract `_run_blocking`) — zero risk, no test surface change, eliminates the drift vector before FIX-C adds a new async call pattern.
2. **FIX-C** (async `summarize_cluster`) — must land before FIX-D so the instrumented call site matches the final async signature.
3. **FIX-D** (OTel spans) — depends on FIX-C call site being stable.
4. **FIX-A** (Redis namespacing) — highest risk; implement last in the hot-path group so the test suite is fully green before introducing the tenant-prefix contract change.
5. **FIX-E** (eval budget check) — independent; can run in parallel with FIX-A.
6. **FIX-F** (document `/metrics` contract) — comment-only; run last, no risk.

**Modification required:** Before FIX-A is implemented, confirm that `RateLimitMiddleware` has access to `request.state.tenant_id` and define the fallback key format for unauthenticated paths. If `tenant_id` is unavailable on the `/webhook` path (which is JWT-exempt), using `ratelimit:anonymous:{user_id}` or skipping tenant prefix for that path must be explicitly decided and documented in `app/middleware/rate_limit.py` — not left implicit.

**Blocking item for Phase 9:** ARCH-2 (embedding dimension mismatch, ADR-002 vs live EmbeddingService) is not in Phase 8 but must be the first task created for Phase 9. A 1536-dim schema with a 1024-dim model will silently corrupt the vector index. This is a data integrity risk, not just tech debt.
