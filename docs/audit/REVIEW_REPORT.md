---
# REVIEW_REPORT — Cycle 8
_Date: 2026-03-09 · Scope: T22–T24 (Phase 7 partial)_

## Executive Summary
- Stop-Ship: No
- Phase 6 (T19–T21) complete; Phase 7 partially implemented — T23 ✅ T24 ✅; T22 in-progress (files on disk, not committed).
- Test baseline regressed: 14 failures + 1 error introduced since Cycle 7 (111 pass / 12 skip); current 142 pass / 14 fail / 1 error. REG-1 blocks T22 merge.
- No P0 findings. One new P1 (REG-1: test regressions). One new P2 (ARCH-9: `GET /eval/runs` missing).
- Eval budget enforcement gap confirmed: `eval/runner.py` calls `CostLedger.record()` but omits `check_budget()` before LLM invocation — violates spec §5 rule #6.
- Load test harness (T23) and full observability stack (T24) pass all architecture checks; no new findings.
- CODE-9 / CODE-11 / ARCH-3 open for 3+ cycles; standalone FIX tasks recommended before Phase 8.
- ARCH-4 downgraded from PARTIAL to OPEN: `app/jobs/rca_clusterer.py` confirmed to have zero OTel imports or spans.

## P0 Issues
_None._

## P1 Issues

### REG-1 — 14 test failures introduced since Cycle 7

**Symptom:** Test suite regressed from Cycle 7 baseline (111 pass / 12 skip) to 142 pass / 14 fail / 1 error.
**Evidence:**
- `tests/test_cost_ledger.py` — 3 failures
- `tests/test_isolation.py` — 5 failures
- `tests/test_llm_client.py` — 3 failures
- `tests/test_store.py` — 3 failures + 1 error (sqlalchemy `ProgrammingError`: syntax error near `$1`)

**Root Cause:** Schema or interface changes in in-progress T22 work (eval router + runner) broke pre-existing test assumptions. `ProgrammingError` in `test_store.py` indicates a parameterized query regression likely from T22 schema/migration changes.
**Impact:** T22 cannot be merged; CI is red; regressions span cost ledger, DB isolation, LLM client, and store — high blast radius across core layers.
**Fix:** Root-cause each failure group: (a) `test_cost_ledger.py` — check for changed `CostLedger` interface; (b) `test_store.py` — diagnose `ProgrammingError` on parameterized query; (c) `test_llm_client.py` — check for schema drift in `EvalRunTriggerResponse`; (d) `test_isolation.py` — check RLS/`SET LOCAL` context changes. Fix without modifying existing passing tests.
**Verify:** `pytest tests/ -x -q` returns 0 failures before T22 merge PR is opened.

## P2 Issues

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| ARCH-2 | ADR-002 specifies `VECTOR(1536)` + OpenAI `text-embedding-3-small`; runtime uses `VECTOR(1024)` + Voyage AI `voyage-3-lite` — ADR not updated | `docs/adr/002-vector-database.md:32`, `app/config.py:29` | Open |
| ARCH-3 | `eval/runner.py` calls `CostLedger.record()` but omits `CostLedger.check_budget()` before LLM invocation — spec §5 rule #6 violated | `eval/runner.py:199`, `app/routers/eval.py` | Open |
| ARCH-4 | `app/jobs/rca_clusterer.py` has zero OTel span instrumentation; ADR-004 mandates spans per pipeline stage | `app/jobs/rca_clusterer.py:177`, `app/jobs/rca_clusterer.py:191` | Open |
| ARCH-5 | `GET /metrics` exempt from JWT auth, no RBAC; per-tenant labels publicly readable — violates spec §5 assumption #2 | `app/main.py:364-366`, `app/middleware/auth.py:55` | Open |
| ARCH-6 | `GET /clusters/{cluster_id}` returns tickets via time-window heuristic, not persisted membership — approximate results | `app/routers/clusters.py:151-175` | Open |
| ARCH-7 | `app/agent.py` imports `HTTPException` from FastAPI at module level — service/transport boundary violation | `app/agent.py:15` | Open |
| ARCH-8 | `app/routers/auth.py` carries bcrypt + JWT business logic; `app/routers/eval.py` carries direct DB INSERT — no service layer exists | `app/routers/auth.py:26-96`, `app/routers/eval.py:77-95` | Open |
| ARCH-9 | `GET /eval/runs` entirely absent from `app/routers/eval.py`; spec §8 AC-2 unimplemented | `app/routers/eval.py` | NEW |
| CODE-5 | Silent broad exception in `_fetch_embeddings` swallows ANN fallback error — no warning or traceback | `app/jobs/rca_clusterer.py:228` | Open |
| CODE-8 | ANN fallback exception branch has no direct unit test | `tests/test_rca_clusterer.py` | Open |
| CODE-9 | Blocking sync `summarize` call inside async RCA path — risks event-loop stall | `app/jobs/rca_clusterer.py:297`, `app/llm_client.py:274` | Open |
| CODE-10 | `/metrics` route has no explicit RBAC/exemption contract documented | `app/main.py:362`, `app/middleware/auth.py:54` | Open |
| CODE-11 | Redis hot-path keys not tenant-namespaced (`dedup:`, `pending:`, `ratelimit:`) | `app/dedup.py:17`, `app/approval_store.py:25`, `app/middleware/rate_limit.py:95` | Open |
| CODE-12 | Import-time `get_settings()` coupling requires `ANTHROPIC_API_KEY` at module load | `app/main.py:223` | Open |
| P2-9 | `_run_blocking()` helper duplicated across `app/agent.py` and `app/store.py` | `app/agent.py`, `app/store.py` | Open |

## Carry-Forward Status

| ID | Sev | Description | Status | Change |
|----|-----|-------------|--------|--------|
| ARCH-1 | P1 | ADR-003/runtime HS256 contract alignment | CLOSED | Closed Cycle 7 |
| CODE-3 | P2 | `tenant_id_hash` logging missing | CLOSED | Closed Cycle 7 |
| CODE-4 | P2 | Bearer literal in app/ scope | CLOSED | Closed Cycle 7 |
| CODE-6 | P2 | Negative cross-tenant test absent | CLOSED | Closed Cycle 7 |
| CODE-7 | P2 | Empty-tools `tool_choice` crash | CLOSED | Closed Cycle 7 |
| REG-1 | P1 | 14 test failures since Cycle 7 | NEW | New this cycle |
| ARCH-9 | P2 | `GET /eval/runs` missing (AC-2 open) | NEW | New this cycle |
| ARCH-2 | P2 | ADR-002 vector stack drift | OPEN | No change |
| ARCH-3 | P2 | Eval LLM cost bypasses CostLedger budget | OPEN | Confirmed in `eval/runner.py:199`; 3rd cycle open |
| ARCH-4 | P2 | RCA OTel span hierarchy incomplete | OPEN | Downgraded from PARTIAL — zero spans confirmed in `rca_clusterer.py` |
| ARCH-5 | P2 | `/metrics` auth/exposure contract drift | OPEN | No change |
| ARCH-6 | P2 | Cluster detail uses time-window heuristic | OPEN | No change |
| ARCH-7 | P2 | `agent.py` HTTPException import (boundary violation) | OPEN | No change |
| ARCH-8 | P2 | Router layer carries business logic | OPEN | New evidence: `eval.py` also affected |
| CODE-5 | P2 | Silent broad exception in `_fetch_embeddings` | OPEN | No change |
| CODE-8 | P3 | ANN fallback exception lacks unit test | OPEN | No change |
| CODE-9 | P2 | Blocking sync summarize in async path | OPEN | 3rd cycle open; recommend standalone FIX task |
| CODE-10 | P2 | `/metrics` RBAC contract undocumented | OPEN | No change |
| CODE-11 | P2 | Redis keys not tenant-namespaced | OPEN | 3rd cycle open; recommend standalone FIX task |
| CODE-12 | P2 | Import-time `get_settings()` coupling | OPEN | No change |
| P2-9 | P2 | `_run_blocking()` duplicated | OPEN | No change |

## Stop-Ship Decision
No — Phase 6 (T19–T21) is complete; no P0 findings. REG-1 blocks T22 merge only; Phase 7 is in-progress and uncommitted. T22 must not be merged until REG-1 (14 test regressions) is resolved.

---
