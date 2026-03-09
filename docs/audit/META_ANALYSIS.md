---
# META_ANALYSIS — Cycle 8
_Date: 2026-03-09 · Type: full_

## Project State
Phase 6 (T19–T21) complete. Next: T22 — Eval REST Endpoint + Per-Tenant Baseline (Phase 7 start).
Baseline: 138 pass, 13 skip (up from 111 pass / 12 skip in Cycle 7 — Phase 6 added 27 tests).

## Open Findings
| ID | Sev | Description | Files | Status |
|----|-----|-------------|-------|--------|
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

_Closed this cycle: ARCH-1 (ADR-003 HS256 contract — aligned and verified)._
_P2-1 and P2-10 consolidated under CODE-11 and CODE-12 respectively._

## PROMPT_1 Scope (architecture)
- **eval subsystem (T22 new)**: `POST /eval/run` + `GET /eval/runs`; eval isolation flag (suppresses ticket writes, skips Linear/Telegram); regression detection via `eval_runs` table (F1 delta > 0.02); cost tracked under `category="eval"` in `cost_ledger` — verify ARCH-3 intersection (eval LLM calls must flow through CostLedger)
- **load test harness (T23 new)**: Locust `load_tests/` directory; `check_kpis.py` KPI assertions (p50 < 2 s, p99 < 8 s, 5xx < 1%); HMAC signing utility in fixture loader
- **docker compose full stack (T24 changed)**: adds Postgres (pgvector), Prometheus, Grafana, Loki, Tempo with health checks and startup ordering
- **carry-forward risk in Phase 7**: CODE-9 (blocking sync summarize) and CODE-11 (Redis namespace) are highest-risk for new eval/load-test paths — eval path may trigger the same async blocking pattern; load test stresses the un-namespaced Redis keys

## PROMPT_2 Scope (code, priority order)
1. `app/routers/eval.py` (new — T22)
2. `eval/runner.py` (changed — T22: `db_session` param added; eval isolation flag)
3. `app/main.py` (changed — T22: eval router included; also CODE-10/CODE-12/ARCH-5 open)
4. `load_tests/locustfile.py`, `load_tests/scenarios/burst.py`, `load_tests/scenarios/steady.py`, `load_tests/check_kpis.py` (new — T23)
5. `docker-compose.yml` (changed — T24)
6. `app/jobs/rca_clusterer.py` (regression: CODE-5, CODE-9, ARCH-3, ARCH-4 all open here)
7. `app/dedup.py`, `app/approval_store.py`, `app/middleware/rate_limit.py` (CODE-11 open)
8. `app/middleware/auth.py` (CODE-10 / ARCH-5: /metrics auth contract)
9. `app/agent.py` (ARCH-7: HTTPException import; P2-9: _run_blocking duplication)

## Cycle Type
Full — Phase 6 is complete (T19–T21 done, ARCH-1 closed). Phase 7 (T22–T24) is the new scope. No targeted hotfix outstanding.

## Notes for PROMPT_3
- Several P2 findings (CODE-9, CODE-11, ARCH-3, ARCH-7, ARCH-8) have been open 3+ cycles; consolidation should recommend whether each warrants a standalone FIX task or can be bundled into the next phase gate.
- T22 eval isolation + cost tracking is the highest-risk new feature: verify that eval LLM calls flow through `CostLedger.check_budget()` and `record()` (closes ARCH-3 intersection), and that output guard still runs (contract requires it on every LLM response).
- Baseline jump (111 → 138 pass) is healthy; confirm no integration-test category was accidentally promoted to unit in Phase 6.
- ARCH-1 closure: all carry-forward tables in docs should reflect CLOSED status before Cycle 9.
---
