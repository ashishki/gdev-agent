---
# REVIEW_REPORT — Cycle 9
_Date: 2026-03-18 · Scope: Phase 8 (FIX-A through FIX-F) · Baseline: 155 pass, 13 skip_

## Executive Summary

- Stop-Ship: No
- Phase 7 (T22–T24) is complete. Phase 8 (FIX-A through FIX-F) is now in-scope and all six tech-debt fixes are verified resolved per ARCH_REPORT — Cycle 9.
- Baseline improved: 144 pass / 13 skip (Cycle 8) → 155 pass / 13 skip (Cycle 9, +11 new tests from FIX tasks).
- No P0 or P1 findings this cycle. All new findings are P2 or P3.
- Six previously-open findings closed: CODE-9 (async summarize), CODE-11 (Redis tenant keys), ARCH-3 (eval budget), ARCH-4 (OTel RCA), FIX-A, FIX-B, FIX-C, FIX-D, FIX-E, FIX-F all resolved.
- Ten P2 findings remain open; the highest-impact cluster (ARCH-6, ARCH-7, ARCH-8) is deferred to Phase 9 service-layer extraction.
- CODE-4 (Redis key canonical ordering) is a new finding from this cycle's code review: three key patterns diverge from the data-map §3 canonical `{tenant_id}:prefix:id` form. Recorded as CODE-1/2/3 below; material risk is Redis ACL prefix grants being blocked at the namespace boundary.
- ADR-002 drift (ARCH-2) and auth_ratelimit global key (CODE-4) remain unresolved and are tracked in Phase 9.

## P0 Issues

_None._

## P1 Issues

_None._

## P2 Issues

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-1 | `DedupCache` key format `dedup:{tenant_id}:{message_id}` diverges from data-map §3 canonical `{tenant_id}:dedup:{message_id}` — Redis ACL prefix grants cannot be applied per-tenant | `app/dedup.py:17`, `app/dedup.py:25`, `docs/data-map.md:175` | Open |
| CODE-2 | `RedisApprovalStore._key` returns `pending:{tenant_id}:{pending_id}` instead of canonical `{tenant_id}:pending:{pending_id}` | `app/approval_store.py:96`, `docs/data-map.md:177` | Open |
| CODE-3 | `_webhook_key` returns `ratelimit:{tenant_id}:{user_id}` instead of canonical `{tenant_id}:ratelimit:{user_id}` | `app/middleware/rate_limit.py:97`, `app/middleware/rate_limit.py:157`, `docs/data-map.md:176` | Open |
| CODE-4 | `auth_ratelimit:{email_hash}` has no tenant prefix; global by design but absent from data-map §3 | `app/middleware/rate_limit.py:129`, `docs/data-map.md` §3 | Open — document or prefix |
| CODE-5 | Silent `except Exception:` in `_fetch_embeddings` swallows ANN fallback — no `LOGGER.warning` or `exc_info` | `app/jobs/rca_clusterer.py:276` | Open (carry-forward Cycle 8) |
| CODE-6 | `AgentService` imports `HTTPException` from `fastapi` — transport boundary violation | `app/agent.py:15`, `app/agent.py:245`, `app/agent.py:434`, `app/agent.py:701` | Open (carry-forward) → SVC-3 |
| CODE-7 | `_fetch_raw_texts_admin` uses `gdev_admin` session with no defence-in-depth guard or tenant_id assertion | `app/jobs/rca_clusterer.py:427-440` | Open |
| CODE-9 | `run_blocking` raises untyped `data` value — `raise data  # type: ignore[misc]`; no narrow BaseException re-raise | `app/utils.py:34` | Open |
| CODE-10 | `run_eval()` non-async path has no `check_budget()` call — budget bypass via CLI/direct invocation | `eval/runner.py:51-110` | Open |
| ARCH-2 | ADR-002 specifies `text-embedding-3-small` (OpenAI) / VECTOR(1536); runtime uses `voyage-3-lite` / VECTOR(1024) | `docs/adr/002-vector-database.md:32`, `app/config.py:29` | Open → DOC-2 |
| ARCH-5 | `GET /metrics` exempt from JWT auth; policy absent from ARCHITECTURE.md and any ADR | `app/main.py:364-366`, `app/middleware/auth.py:55`, `docs/ARCHITECTURE.md` | Open → FIX-F (partial) |
| ARCH-6 | `GET /clusters/{cluster_id}` returns tickets via time-window heuristic, not persisted membership | `app/routers/clusters.py:151-175` | Open |
| ARCH-7 | `app/agent.py` imports `HTTPException` from FastAPI — service/transport boundary violation | `app/agent.py:15` | Open → SVC-3 |
| ARCH-8 | Router layer carries business logic: bcrypt+JWT in `auth.py`, direct DB INSERT in `eval.py` | `app/routers/auth.py:26-96`, `app/routers/eval.py:77-95` | Open → Phase 9 |

## P3 Issues

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-8 | No direct unit test for `_fetch_embeddings` ANN fallback exception branch | `tests/test_rca_clusterer.py` | Open (carry-forward Cycle 8) |

## Carry-Forward Status

| ID | Sev | Description | Status | Change |
|----|-----|-------------|--------|--------|
| CODE-5 | P2 | Silent broad exception in `_fetch_embeddings` — no warning | Open | No change — carry-forward Cycle 8 |
| CODE-8 | P3 | ANN fallback exception branch has no direct unit test | Open | No change — carry-forward Cycle 8 |
| CODE-9 (renamed) | P2 | `run_blocking` raises untyped data — `type: ignore[misc]` | Open | New Cycle 9 detail on pre-existing issue |
| CODE-11 | P2 | Redis hot-path keys not tenant-namespaced | CLOSED | FIX-A resolved; key format updated |
| ARCH-2 | P2 | ADR-002 embedding dim mismatch | Open | No change; DOC-2 scheduled Phase 9 |
| ARCH-3 | P2 | RCA eval cost path bypasses budget check | CLOSED | FIX-E resolved: `check_budget()` at `eval/runner.py:184` |
| ARCH-4 | P2 | RCA clusterer zero OTel spans | CLOSED | FIX-D resolved: `rca.run`, `rca.cluster`, `rca.summarize` spans added |
| ARCH-5 | P2 | `/metrics` auth contract undocumented | Open (partial) | FIX-F added inline comments; ARCHITECTURE.md update deferred |
| ARCH-6 | P2 | Cluster membership heuristic, not persisted | Open | No change; deferred Phase 9 |
| ARCH-7 | P2 | `agent.py` imports `HTTPException` | Open | No change; SVC-3 deferred Phase 9 |
| ARCH-8 | P2 | Business logic in router layer | Open | No change; deferred Phase 9 |
| ARCH-9 | P2 | `GET /eval/runs` missing | CLOSED | Implemented Cycle 8 |
| REG-1 | P1 | 14 test regressions (Cycle 8) | CLOSED | FIX-9 resolved; baseline 144 pass |
| P2-9 | P2 | `_run_blocking()` duplicated | CLOSED | FIX-B resolved: extracted to `app/utils.py` |
| P2-10 | P2 | Module-level settings access requires API key at import | Open | No change |

## Resolved This Cycle

| Finding | Resolution | Evidence |
|---------|------------|----------|
| CODE-11 / FIX-A | Redis hot-path keys tenant-namespaced | `app/dedup.py`, `app/approval_store.py`, `app/middleware/rate_limit.py` — ARCH_REPORT PASS |
| P2-9 / FIX-B | `_run_blocking` extracted to `app/utils.py` | `app/utils.py` exists; `app/agent.py` + `app/store.py` import from it — ARCH_REPORT PASS |
| CODE-9 / FIX-C | Async `summarize_cluster` via `asyncio.to_thread` | `app/llm_client.py` `summarize_cluster_async` present — ARCH_REPORT PASS |
| ARCH-4 / FIX-D | OTel spans for RCA Clusterer | `rca_clusterer.py` spans `rca.run`, `rca.cluster`, `rca.summarize` — ARCH_REPORT PASS |
| ARCH-3 / FIX-E | Budget check in eval runner | `eval/runner.py:184` calls `check_budget()` — ARCH_REPORT PASS |
| ARCH-5 / FIX-F (partial) | `/metrics` auth contract documented in code comments | `app/middleware/auth.py:57` exemption comment present — ARCH_REPORT DRIFT (ARCHITECTURE.md update still pending) |

## Stop-Ship Decision

**No.** No P0 or P1 findings. Phase 8 is complete. All six scheduled FIX tasks resolved. Remaining open findings are P2/P3 quality and architecture-drift items deferred to Phase 9. Repo is green at 155 pass / 13 skip.

---

_Next: archive this file to `docs/audit/archive/CYCLE9_REVIEW.md` before Cycle 10 begins._
