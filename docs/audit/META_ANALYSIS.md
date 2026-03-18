---
# META_ANALYSIS — Cycle 11
_Date: 2026-03-18 · Type: full_

## Project State

Phase 9 (FIX-G, SVC-1, SVC-2, SVC-3, DOC-1, DOC-2, DOC-3) complete. Next: CLI-1 — Typer admin CLI (Phase 10 start).
Documented baseline: 168 pass, 13 skip. Actual measured baseline: 167 pass, 14 fail, 0 skip — **14 regressions detected** (test_cost_ledger ×3, test_isolation ×5, test_llm_client ×3, test_store ×3, 1 error). Delta from Cycle 9: -1 pass, +14 fail, -13 skip. This is a stop-ship candidate; must be confirmed before Phase 10 begins.

## Open Findings

| ID | Sev | Description | Files | Status |
|----|-----|-------------|-------|--------|
| REG-2 | P1 | 14 test failures in test_cost_ledger, test_isolation, test_llm_client, test_store — repo NOT green despite CODEX_PROMPT claiming 168 pass / 13 skip | `tests/test_cost_ledger.py`, `tests/test_isolation.py`, `tests/test_llm_client.py`, `tests/test_store.py` | **NEW — open, must fix before CLI-1** |
| CODE-4 | P2 | `auth_ratelimit:{email_hash}` has no tenant prefix; global by design but absent from data-map §3 | `app/middleware/rate_limit.py:129`, `docs/data-map.md §3` | Open — document or add to data-map |
| CODE-5 | P2 | Silent `except Exception:` in `_fetch_embeddings` swallows ANN fallback — no `LOGGER.warning` or `exc_info` | `app/jobs/rca_clusterer.py:276` | Open (carry-forward Cycles 8–10) |
| CODE-7 | P2 | `_fetch_raw_texts_admin` uses `gdev_admin` session with no defence-in-depth guard or `tenant_id` assertion | `app/jobs/rca_clusterer.py:427-440` | Open |
| CODE-8 | P3 | No direct unit test for `_fetch_embeddings` ANN fallback exception branch | `tests/test_rca_clusterer.py` | Open (carry-forward Cycles 8–10) |
| CODE-9 | P2 | `run_blocking` raises untyped `data` value — `raise data  # type: ignore[misc]`; no narrow `BaseException` re-raise | `app/utils.py:34` | Open (carry-forward) |
| CODE-10 | P2 | `run_eval()` non-async path has no `check_budget()` call — budget bypass via CLI/direct invocation | `eval/runner.py:51-110` | Open |
| CODE-12 | P2 | Module-level `get_settings()` coupling requires `ANTHROPIC_API_KEY` at import time | `app/main.py:223` | Open (carry-forward as P2-10) |
| ARCH-2 | P2 | ADR-002 specifies `text-embedding-3-small` (OpenAI) / VECTOR(1536); runtime uses `voyage-3-lite` / VECTOR(1024) | `docs/adr/002-vector-database.md:32`, `app/config.py:29` | Open — DOC-2 updated ADR but mismatch persists |
| ARCH-5 | P2 | `/metrics` exempt from JWT auth; policy absent from ARCHITECTURE.md and any ADR | `app/main.py:364-366`, `app/middleware/auth.py:55` | Open (partial — inline comments added by FIX-F; ARCHITECTURE.md update done in DOC-1) |
| ARCH-6 | P2 | `GET /clusters/{cluster_id}` returns tickets via time-window heuristic, not persisted membership | `app/routers/clusters.py:151-175` | Open → CLU-1 (Phase 10) |

## PROMPT_1 Scope (architecture)

- Regression root cause: 14 failing tests span cost_ledger, isolation, llm_client, store — likely a Phase 9 interface or schema change broke existing contracts; identify before Phase 10 work begins
- Service layer (Phase 9 complete): verify AuthService + EvalService extraction is clean — no transport imports in `app/agent.py`, no business logic in router layer; confirm SVC-1/SVC-2/SVC-3 acceptance criteria met at runtime
- CLI-1 design: Typer CLI at `scripts/cli.py` covers tenant + budget operations and triggers RCA job; assess whether CLI shares service layer (app/services/) or bypasses it (direct DB access)
- CLU-1 design: new `rca_cluster_members` table + migration 0003; assess RLS policy placement and whether clusterer admin session write pattern matches existing patterns in `app/jobs/rca_clusterer.py`
- ARCH-6 (heuristic membership): CLU-1 is the Phase 10 fix; confirm no other callers of the timestamp heuristic path remain after CLU-1

## PROMPT_2 Scope (code, priority order)

1. `tests/test_cost_ledger.py`, `tests/test_isolation.py`, `tests/test_llm_client.py`, `tests/test_store.py` — diagnose 14 failures; REG-2 (new P1)
2. `app/services/auth_service.py` (new — SVC-1 Phase 9)
3. `app/services/eval_service.py` (new — SVC-2 Phase 9)
4. `app/routers/auth.py` (changed — SVC-1 extraction)
5. `app/routers/eval.py` (changed — SVC-2 extraction)
6. `app/agent.py` (changed — SVC-3 HTTPException removal)
7. `app/exceptions.py` (new or changed — SVC-3 domain exceptions)
8. `eval/runner.py` (CODE-10 — budget bypass in non-async path; regression check)
9. `app/utils.py` (CODE-9 — untyped re-raise; regression check)
10. `app/jobs/rca_clusterer.py` (CODE-5 silent exception, CODE-7 admin session guard — carry-forward)
11. `app/middleware/rate_limit.py` (CODE-4 — auth_ratelimit key absent from data-map)
12. `app/main.py` (CODE-12 import-time settings coupling — regression check)

## Cycle Type

Full — Phase 9 complete, next phase boundary (Phase 10 CLI-1). However, 14 test regressions discovered; cycle must resolve REG-2 before Phase 10 tasks begin. Treat as full cycle with mandatory regression triage.

## Notes for PROMPT_3

- REG-2 is the critical blocker: 14 failures across 4 test files. Root cause likely in Phase 9 service-layer extraction (SVC-1/SVC-2) or FIX-G key reordering changing expected values in tests. PROMPT_3 must confirm whether these are fixable in a single FIX-H or require a broader regression sweep.
- CODE-10 (budget bypass in `run_eval()` non-async path) remains open and is high-impact for CLI-1 since the new CLI will have a direct `rca run` command — same bypass risk applies to any new CLI-triggered eval path.
- ARCH-6 (heuristic cluster membership) is the P2 driver for CLU-1; PROMPT_3 should confirm no integration tests depend on the heuristic behaviour before CLU-1 replaces it.
- CODE-9 (`run_blocking` untyped re-raise) is a low-effort fix; PROMPT_3 should recommend bundling into FIX-H if a regression fix task is created.
- Documented baseline (168 pass, 13 skip) in CODEX_PROMPT v3.10 does not match measured baseline (167 pass, 14 fail). PROMPT_3 should flag the discrepancy and update CODEX_PROMPT after REG-2 is resolved.
---
