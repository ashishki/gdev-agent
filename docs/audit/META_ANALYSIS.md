---
# META_ANALYSIS — Cycle 10
_Date: 2026-03-18 · Type: full_

## Project State

Phase 8 (FIX-A through FIX-F) complete. Next: FIX-G — Invert Redis key segment order to `{tenant_id}:{type}:{id}` (Phase 9 start).
Baseline: 155 pass, 13 skip (Cycle 9 +11 vs Cycle 8 144/13; no regressions).

## Open Findings

| ID | Sev | Description | Files | Status |
|----|-----|-------------|-------|--------|
| CODE-1 | P2 | `DedupCache` key `dedup:{tenant_id}:{message_id}` diverges from data-map §3 canonical `{tenant_id}:dedup:{message_id}` — Redis ACL prefix grants blocked at namespace boundary | `app/dedup.py:17,25`, `docs/data-map.md:175` | Open → FIX-G |
| CODE-2 | P2 | `RedisApprovalStore._key` returns `pending:{tenant_id}:{pending_id}` instead of `{tenant_id}:pending:{pending_id}` | `app/approval_store.py:96`, `docs/data-map.md:177` | Open → FIX-G |
| CODE-3 | P2 | `_webhook_key` returns `ratelimit:{tenant_id}:{user_id}` instead of `{tenant_id}:ratelimit:{user_id}` | `app/middleware/rate_limit.py:97,157`, `docs/data-map.md:176` | Open → FIX-G |
| CODE-4 | P2 | `auth_ratelimit:{email_hash}` has no tenant prefix; global by design but absent from data-map §3 | `app/middleware/rate_limit.py:129`, `docs/data-map.md §3` | Open — document or prefix |
| CODE-5 | P2 | Silent `except Exception:` in `_fetch_embeddings` swallows ANN fallback — no `LOGGER.warning` or `exc_info` | `app/jobs/rca_clusterer.py:276` | Open (carry-forward Cycle 8) |
| CODE-6 | P2 | `AgentService` imports `HTTPException` from `fastapi` — service/transport boundary violation | `app/agent.py:15,245,434,701` | Open → SVC-3 |
| CODE-7 | P2 | `_fetch_raw_texts_admin` uses `gdev_admin` session with no defence-in-depth guard or `tenant_id` assertion | `app/jobs/rca_clusterer.py:427-440` | Open |
| CODE-8 | P3 | No direct unit test for `_fetch_embeddings` ANN fallback exception branch | `tests/test_rca_clusterer.py` | Open (carry-forward Cycle 8) |
| CODE-9 | P2 | `run_blocking` raises untyped `data` — `raise data  # type: ignore[misc]`; no narrow `BaseException` re-raise | `app/utils.py:34` | Open |
| CODE-10 | P2 | `run_eval()` non-async path has no `check_budget()` call — budget bypass via CLI/direct invocation | `eval/runner.py:51-110` | Open |
| CODE-12 | P2 | Module-level `get_settings()` coupling requires `ANTHROPIC_API_KEY` at import time | `app/main.py:223` | Open (carry-forward as P2-10) |
| ARCH-2 | P2 | ADR-002 specifies `text-embedding-3-small` (OpenAI) / VECTOR(1536); runtime uses `voyage-3-lite` / VECTOR(1024) | `docs/adr/002-vector-database.md:32`, `app/config.py:29` | Open → DOC-2 |
| ARCH-5 | P2 | `/metrics` exempt from JWT auth; policy absent from ARCHITECTURE.md and any ADR | `app/main.py:364-366`, `app/middleware/auth.py:55`, `docs/ARCHITECTURE.md` | Open (partial) → DOC-1 |
| ARCH-6 | P2 | `GET /clusters/{cluster_id}` returns tickets via time-window heuristic, not persisted membership | `app/routers/clusters.py:151-175` | Open → CLU-1 |
| ARCH-7 | P2 | `app/agent.py` imports `HTTPException` from FastAPI — service/transport boundary violation | `app/agent.py:15` | Open → SVC-3 |
| ARCH-8 | P2 | Router layer carries business logic: bcrypt+JWT in `auth.py`, direct DB INSERT in `eval.py` | `app/routers/auth.py:26-96`, `app/routers/eval.py:77-95` | Open → SVC-1, SVC-2 |

## PROMPT_1 Scope (architecture)

- Redis key namespace: FIX-G inverts segment order in dedup, approval_store, rate_limit — verify no cross-tenant key collision risk and confirm data-map §3 alignment post-change
- Service layer extraction: SVC-1 (AuthService), SVC-2 (EvalService), SVC-3 (agent.py boundary) — assess import graph and identify all callsites before any refactor
- Auth router business logic: bcrypt+JWT assembly and DB writes in router scope — define service interface boundaries for SVC-1
- Eval router business logic: direct DB INSERT in `eval.py` — define service interface boundaries for SVC-2
- Budget bypass via CLI: `run_eval()` non-async path skips `check_budget()` — risk of uncapped LLM spend; assess severity relative to stop-ship threshold
- ARCHITECTURE.md staleness: v2.1 missing eval subsystem, service layer, Phase 8 fixes, Docker stack — DOC-1 is Phase 9 final task

## PROMPT_2 Scope (code, priority order)

1. `app/dedup.py` (new change target — FIX-G key inversion)
2. `app/approval_store.py` (new change target — FIX-G key inversion)
3. `app/middleware/rate_limit.py` (new change target — FIX-G key inversion + CODE-4 auth_ratelimit doc gap)
4. `app/routers/auth.py` (SVC-1 extraction target — ARCH-8)
5. `app/routers/eval.py` (SVC-2 extraction target — ARCH-8)
6. `app/agent.py` (SVC-3 target — ARCH-7 HTTPException import + CODE-6)
7. `app/utils.py` (CODE-9 — untyped re-raise in `run_blocking`)
8. `eval/runner.py` (CODE-10 — budget bypass in non-async path)
9. `app/jobs/rca_clusterer.py` (CODE-5 silent exception, CODE-7 admin session guard — regression check)
10. `app/main.py` (CODE-12 import-time settings coupling — regression check)

## Cycle Type

Full — Phase 8 is complete, baseline is stable at 155/13, no in-flight tasks. Cycle 10 opens Phase 9 work starting with FIX-G.

## Notes for PROMPT_3

- FIX-G (key inversion) must be verified for test coverage of cross-tenant isolation: all three key patterns (`dedup:`, `pending:`, `ratelimit:`) must have before/after assertions in tests.
- CODE-10 (budget bypass in `run_eval()` non-async path) should be assessed for stop-ship severity — CLI invocation bypassing budget is a spend-control gap even if not a security hole.
- ARCH-8 (business logic in routers) spans two tasks (SVC-1, SVC-2) — consolidation should confirm no behavioral regression, only structural movement; flag any logic silently duplicated across layers.
- If CODE-9 (`run_blocking` untyped re-raise) is not addressed in FIX-G, recommend adding a narrow `BaseException` check to remove `type: ignore[misc]` without breaking the async bridge contract.
- ARCHITECTURE.md v2.1 is stale (missing eval subsystem, service layer, Phase 8 fixes, Docker stack) — DOC-1 is the last Phase 9 task; PROMPT_3 should flag any architectural facts captured only in code comments, not yet in docs.
---
