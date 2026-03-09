---
# META_ANALYSIS — Cycle 8
_Date: 2026-03-09 · Type: full_

## Project State
Phase 6 (T19–T21) complete. Phase 7 in progress: T23 ✅ T24 ✅ · T22 in-progress (files on disk, not committed).
Next confirmed task: complete T22 (Eval REST Endpoint + Per-Tenant Baseline).
Baseline: **14 failed, 142 passed, 1 error** — regression vs Cycle 7 (111 pass / 12 skip).
Regression files: `tests/test_cost_ledger.py` (3), `tests/test_isolation.py` (5), `tests/test_llm_client.py` (3), `tests/test_store.py` (3 + 1 error).

## Open Findings
| ID | Sev | Description | Files | Status |
|----|-----|-------------|-------|--------|
| REG-1 | P1 | 14 test failures introduced since Cycle 7 — must resolve before T22 merge | `tests/test_cost_ledger.py`, `tests/test_isolation.py`, `tests/test_llm_client.py`, `tests/test_store.py` | NEW |
| CODE-5 | P2 | Silent broad exception in `_fetch_embeddings` — no warning/traceback on ANN fallback | `app/jobs/rca_clusterer.py:228` | Open |
| CODE-8 | P3 | ANN fallback exception branch lacks direct unit test | `tests/test_rca_clusterer.py` | Open |
| CODE-9 | P2 | Blocking sync `summarize` call in async RCA path — risks event-loop stall | `app/jobs/rca_clusterer.py:297`, `app/llm_client.py:274` | Open |
| CODE-10 | P2 | `/metrics` route has no explicit RBAC/exemption contract | `app/main.py:362`, `app/middleware/auth.py:54` | Open |
| CODE-11 | P2 | Redis hot-path keys not tenant-namespaced | `app/dedup.py:17`, `app/approval_store.py:25`, `app/middleware/rate_limit.py:95` | Open |
| CODE-12 | P2 | Import-time `get_settings()` coupling requires API key at module load | `app/main.py:223` | Open |
| ARCH-2 | P2 | ADR-002 vector stack drift: docs say OpenAI/1536, runtime uses Voyage/1024 | `docs/adr/002-vector-database.md:32`, `app/config.py:29` | Open |
| ARCH-3 | P2 | RCA summarization LLM cost path bypasses `CostLedger` budget/accounting | `app/jobs/rca_clusterer.py:297`, `app/agent.py:151` | Open |
| ARCH-4 | P2 | RCA OTel background span hierarchy incomplete | `app/jobs/rca_clusterer.py:177`, `app/jobs/rca_clusterer.py:191` | Partial |
| ARCH-5 | P2 | `/metrics` exposure/auth contract not reconciled with spec security assumptions | `app/main.py:362`, `docs/spec.md:91` | Open |
| ARCH-6 | P2 | Cluster detail endpoint uses time-window heuristic, not persisted membership | `app/routers/clusters.py:151` | Open |
| ARCH-7 | P2 | `app/agent.py` imports `HTTPException` (transport type) — service/transport boundary violation | `app/agent.py:15` | Open |
| ARCH-8 | P2 | Router layer carries business logic that belongs in service layer | `app/routers/auth.py:26`, `app/main.py:275` | Open |
| P2-9 | P2 | `_run_blocking()` helper duplicated across `app/agent.py` and `app/store.py` | `app/agent.py`, `app/store.py` | Open |

_Closed since Cycle 7: ARCH-1 (HS256 contract aligned), CODE-3, CODE-4, CODE-6, CODE-7._

## PROMPT_1 Scope (architecture)
- **eval subsystem (T22 in-progress)**: `POST /eval/run` + `GET /eval/runs`; async background job via `asyncio.create_task`; eval isolation (suppresses ticket writes, skips Linear/Telegram); cost tracked under `category="eval"` in `cost_ledger` — verify ARCH-3 intersection (eval LLM calls must flow through `CostLedger.check_budget()` and `record()`); `EvalRunTriggerResponse` in schemas; no `GET /eval/runs` implementation found yet (AC-2 open)
- **load test harness (T23 done)**: Locust `load_tests/` with burst/steady scenarios; `check_kpis.py` KPI assertions (p50 < 2s, p99 < 8s, 5xx < 1%); HMAC signing utility in fixture loader
- **docker compose full stack (T24 done)**: adds Postgres (pgvector), Prometheus, Grafana, Loki, Tempo; Grafana datasource provisioning for Loki and Tempo added; seed.sql for test tenants
- **regression risk**: 14 test failures are concentrated in DB isolation, cost ledger, and LLM client tests — likely caused by schema or interface changes in T22/T23/T24 work; must be diagnosed before Phase 7 is declared complete
- **carry-forward risk**: CODE-9 (blocking sync summarize) and CODE-11 (Redis namespace) are highest-risk for new eval/load-test paths — eval path may trigger the same async blocking; load tests stress un-namespaced Redis keys

## PROMPT_2 Scope (code, priority order)
1. `tests/test_cost_ledger.py`, `tests/test_isolation.py`, `tests/test_llm_client.py`, `tests/test_store.py` — **P1: diagnose and fix 14 regressions first**
2. `app/routers/eval.py` (new — T22, in-progress): verify AC-2 (`GET /eval/runs`) missing; eval isolation flag; no ticket writes; cost tracking
3. `eval/runner.py` (changed — T22): `db_session` param added; `run_eval_job` async path; verify `CostLedger` integration
4. `app/main.py` (changed — T22: eval router included; CODE-10/CODE-12/ARCH-5 open)
5. `app/schemas.py` (changed — T22: `EvalRunTriggerResponse` added)
6. `load_tests/locustfile.py`, `load_tests/scenarios/burst.py`, `load_tests/scenarios/steady.py`, `load_tests/check_kpis.py` (new — T23)
7. `docker-compose.yml` (changed — T24)
8. `app/jobs/rca_clusterer.py` (regression check: CODE-5, CODE-9, ARCH-3, ARCH-4 all open)
9. `app/dedup.py`, `app/approval_store.py`, `app/middleware/rate_limit.py` (CODE-11)
10. `app/agent.py` (ARCH-7: HTTPException import; P2-9: _run_blocking duplication)

## Cycle Type
Full — Phase 6 complete (T19–T21 done, ARCH-1 closed). Phase 7 partially implemented (T23/T24 done, T22 in-progress). Test regression is a stop condition for T22 merge.

## Notes for PROMPT_3
- **REG-1 is the critical gate**: 14 failing tests must be root-caused and fixed before T22 merge. The sqlalchemy `ProgrammingError` (syntax error near `$1`) in `test_store.py` suggests a parameterized query issue likely introduced by schema changes. `test_llm_client.py` failures may indicate a changed interface in llm_client or schemas.
- T22 `GET /eval/runs` endpoint appears unimplemented (only `POST /eval/run` exists in `app/routers/eval.py`) — AC-2 is open.
- Eval `run_eval` function (sync, legacy) and `run_eval_job` (async, new) coexist in `eval/runner.py` — check whether the sync path is still needed or can be retired.
- CODE-9/CODE-11/ARCH-3 have been open 3+ cycles; consolidation should recommend standalone FIX tasks before Phase 8.
- Baseline jump from Cycle 7 (111 pass) to current (142 pass) is partially inflated by new T22/T23 test files; the 14 regressions likely represent pre-existing tests broken by interface drift.
---
