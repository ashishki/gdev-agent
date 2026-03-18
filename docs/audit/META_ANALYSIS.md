---
# META_ANALYSIS — Cycle 9
_Date: 2026-03-18 · Type: targeted_

## Project State
Phase 7 (T22–T24) complete; FIX-9 (REG-1) resolved. Next: FIX-A — Tenant-namespace Redis hot-path keys (Phase 8 start).
Baseline: 144 pass, 13 skip.

Baseline change vs Cycle 8: regressions fully resolved (+2 pass net, 14 fail → 0 fail, 1 error → 0 error).

## Open Findings

| ID | Sev | Description | Files | Status |
|----|-----|-------------|-------|--------|
| CODE-5 | P2 | Silent broad exception in `_fetch_embeddings` swallows ANN fallback — no warning/traceback | `app/jobs/rca_clusterer.py:228` | Open |
| CODE-8 | P3 | ANN fallback exception branch has no direct unit test | `tests/test_rca_clusterer.py` | Open |
| CODE-9 | P2 | Blocking sync `summarize` call inside async RCA path — risks event-loop stall | `app/jobs/rca_clusterer.py:297`, `app/llm_client.py:274` | Open — FIX-C scheduled |
| CODE-10 | P2 | `/metrics` route has no explicit RBAC/exemption contract documented | `app/main.py:362`, `app/middleware/auth.py:54` | Open — FIX-F scheduled |
| CODE-11 | P2 | Redis hot-path keys not tenant-namespaced (`dedup:`, `pending:`, `ratelimit:`) | `app/dedup.py:17`, `app/approval_store.py:25`, `app/middleware/rate_limit.py:95` | Open — FIX-A scheduled |
| CODE-12 | P2 | Import-time `get_settings()` coupling requires `ANTHROPIC_API_KEY` at module load | `app/main.py:223` | Open — FIX-B adjacent |
| ARCH-2 | P2 | ADR-002 specifies OpenAI/1536; runtime uses Voyage AI/1024 — ADR not updated | `docs/adr/002-vector-database.md:32`, `app/config.py:29` | Open — DOC-2 scheduled |
| ARCH-3 | P2 | `eval/runner.py` calls `CostLedger.record()` but omits `check_budget()` before LLM call — spec §5 rule #6 violated | `eval/runner.py:199`, `app/routers/eval.py` | Open — FIX-E scheduled |
| ARCH-4 | P2 | `app/jobs/rca_clusterer.py` has zero OTel span instrumentation; ADR-004 mandates spans per pipeline stage | `app/jobs/rca_clusterer.py:177`, `app/jobs/rca_clusterer.py:191` | Open — FIX-D scheduled |
| ARCH-5 | P2 | `GET /metrics` exempt from JWT auth, no RBAC; per-tenant labels publicly readable — violates spec §5 assumption #2 | `app/main.py:364-366`, `app/middleware/auth.py:55` | Open — FIX-F scheduled |
| ARCH-6 | P2 | `GET /clusters/{cluster_id}` returns tickets via time-window heuristic, not persisted membership | `app/routers/clusters.py:151-175` | Open |
| ARCH-7 | P2 | `app/agent.py` imports `HTTPException` from FastAPI — service/transport boundary violation | `app/agent.py:15` | Open |
| ARCH-8 | P2 | Router layer carries business logic: bcrypt+JWT in `auth.py`, direct DB INSERT in `eval.py` — no service layer | `app/routers/auth.py:26-96`, `app/routers/eval.py:77-95` | Open |
| P2-9 | P2 | `_run_blocking()` helper duplicated across `app/agent.py` and `app/store.py` | `app/agent.py`, `app/store.py` | Open — FIX-B scheduled |

_Closed since Cycle 8: REG-1 (FIX-9 resolved all 14 regressions), ARCH-9 (`GET /eval/runs` implemented in `app/routers/eval.py`)._

## PROMPT_1 Scope (architecture)

- Phase 8 entry: all six FIX tasks (FIX-A through FIX-F) pending; repo clean — no uncommitted changes
- Redis namespace isolation: cross-tenant key collision risk in dedup, approval, and rate-limit hot paths (FIX-A)
- Async correctness: blocking sync `summarize` call in async RCA path — event-loop stall risk under load (FIX-C)
- Observability gap: zero OTel spans in `rca_clusterer.py` despite ADR-004 mandate — entire job is dark (FIX-D)
- Budget enforcement gap: eval LLM calls bypass `check_budget()` — spec §5 rule #6 violated (FIX-E)
- Auth contract drift: `/metrics` publicly readable, no RBAC policy documented or enforced (FIX-F)
- Code duplication: `_run_blocking()` exists in two modules; FIX-B extracts to shared utility
- Service layer absent: ARCH-8 blocks clean service extraction in Phase 9 (SVC-1 through SVC-3)

## PROMPT_2 Scope (code, priority order)

1. `app/dedup.py` (FIX-A — add tenant-prefix to Redis keys)
2. `app/approval_store.py` (FIX-A — add tenant-prefix to Redis keys)
3. `app/middleware/rate_limit.py` (FIX-A — add tenant-prefix to Redis keys)
4. `app/agent.py` + `app/store.py` (FIX-B — extract `_run_blocking` to shared utility)
5. `app/jobs/rca_clusterer.py` (FIX-C + FIX-D — async summarize fix + OTel spans)
6. `eval/runner.py` (FIX-E — add `check_budget()` before LLM invocation)
7. `app/main.py` + `app/middleware/auth.py` (FIX-F — document and enforce `/metrics` auth contract)
8. `app/llm_client.py` (regression check — touched by FIX-C async path)
9. `tests/test_rca_clusterer.py` (CODE-8 — add direct unit test for ANN fallback exception branch)

## Cycle Type
Targeted — no new feature tasks; this cycle covers six isolated tech-debt fixes (FIX-A through FIX-F) that have been open 3+ review cycles and are now formally scheduled as Phase 8.

## Notes for PROMPT_3
- Consolidation focus: verify each FIX-A through FIX-F explicitly closes its corresponding finding ID; none should carry forward.
- FIX-A changes Redis key format — watch for regressions in `tests/test_dedup.py`, `tests/test_approval_store.py`, `tests/test_rate_limit.py`; any test asserting raw key strings must be updated.
- FIX-B (`_run_blocking` extraction) touches both `app/agent.py` and `app/store.py` — run full isolation test suite after.
- FIX-C (async RCA) and FIX-D (OTel) both modify `app/jobs/rca_clusterer.py` — coordinate or sequence to avoid merge conflict.
- ARCH-6 (cluster membership heuristic) and ARCH-8 (service layer) remain out of scope for Cycle 9; flag if any FIX task inadvertently refactors those paths.
- CODE-8 (ANN fallback coverage) is P3 and may be bundled with FIX-C/FIX-D rather than a standalone task.
---
