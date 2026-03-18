---
# REVIEW_REPORT — Cycle 11
_Date: 2026-03-18 · Scope: Phase 9 (FIX-G, SVC-1, SVC-2, SVC-3, DOC-1, DOC-2, DOC-3) · Baseline: 167 pass, 14 fail, 0 skip_

## Executive Summary

- Stop-Ship: **Yes** — 14 test regressions (REG-2) block Phase 10 start; root cause confirmed as CODE-1 (`SET LOCAL` parameterized binding rejected by asyncpg).
- Phase 9 is nominally complete (7/7 tasks done: FIX-G ✅, SVC-1 ✅, SVC-2 ✅, SVC-3 ✅, DOC-1 ✅, DOC-2 ✅, DOC-3 ✅) but the service-layer extraction introduced a regression across 4 test files.
- Documented baseline in CODEX_PROMPT v3.10 (168 pass / 13 skip) does not match measured baseline (167 pass / 14 fail / 0 skip). CODEX_PROMPT must be corrected after FIX-H resolves REG-2.
- CODE-1 (`SET LOCAL` with bound parameter `:tid` rejected by asyncpg; only literal string form accepted) is the confirmed root cause of all 14 REG-2 failures spanning `test_cost_ledger`, `test_isolation`, `test_llm_client`, `test_store`.
- SVC-1 is partially non-compliant: `AuthService` imports `JSONResponse` from `fastapi.responses` (transport type leaks across layer boundary); `POST /auth/logout` and `POST /auth/refresh` exist in AuthService but have no registered routes.
- ADR compliance is otherwise strong: ADR-001 ✅, ADR-002 ✅ (DOC-2 resolved ARCH-2), ADR-003 ✅ (HS256 v1 choice documented), ADR-004 ✅, ADR-005 ✅.
- P1-1 in MEMORY.md ("HS256 vs RS256 conflict") is a misread of ADR-003; ADR-003 §Consequences explicitly accepts HS256 for v1 with RS256 migration path documented. P1-1 is closed.
- Eight P2 findings remain open; none are blocking independently (CODE-1/REG-2 is the sole stop-ship trigger).

---

## P0 Issues

### P0-1 (CODE-1) — `SET LOCAL` with bound parameters rejected by asyncpg

**Symptom:** 14 test failures across `tests/test_cost_ledger.py` (×3), `tests/test_isolation.py` (×5), `tests/test_llm_client.py` (×3), `tests/test_store.py` (×3 + 1 error). Tests that previously passed regressed after Phase 9 service-layer extraction.

**Evidence:** asyncpg does not accept parameterized form `text("SET LOCAL app.current_tenant_id = :tid", {"tid": str(tenant_id)})`. The driver requires a literal string statement; bind parameters are not supported for `SET LOCAL`. Sites:
- `app/store.py:121`
- `app/db.py:46`
- `app/approval_store.py:106`
- `app/agent.py:687, 717, 800`
- `app/embedding_service.py:94`
- `app/services/eval_service.py:98, 119, 398`
- `app/jobs/rca_clusterer.py:251, 279, 306, 375`
- `eval/runner.py`

**Root Cause:** asyncpg rejects `SET LOCAL ... = :param` because `SET` is not a parameterizable statement. The Phase 9 refactor (SVC-1/SVC-2) likely introduced new `SET LOCAL` call sites using the parameterized form, or an existing helper was changed.

**Impact:** All DB-touching tests that exercise `SET LOCAL` fail. Tenant isolation, cost ledger, LLM client, and store tests are all broken. The repo is NOT green. Phase 10 cannot begin.

**Fix:** Replace all parameterized `SET LOCAL` calls with f-string interpolation using a pre-validated UUID:
```python
text(f"SET LOCAL app.current_tenant_id = '{UUID(str(tid))}'")
```
Extract to a shared helper `_set_tenant_ctx(session, tid)` in `app/db.py` and call from all 10+ sites. The `UUID(str(tid))` constructor enforces format before interpolation, preventing injection.

**Verify:** `pytest tests/ -q` must return 0 failures. Cross-tenant isolation test (`tests/test_isolation.py`) must pass. SQL injection via malformed `tid` is blocked by `UUID()` constructor raising `ValueError`.

**Assigned task:** FIX-H

---

## P1 Issues

### P1-1 (CODE-2) — AuthService imports `JSONResponse`: transport type in service layer

**Symptom:** `app/services/auth_service.py:13` contains `from fastapi.responses import JSONResponse`. `_ServiceResult.to_response()` constructs and returns a `JSONResponse` instance.

**Evidence:** `app/services/auth_service.py:13` (import), `app/services/auth_service.py:87` (construction). ARCH_REPORT — Cycle 11 verdict: DRIFT.

**Root Cause:** SVC-1 extracted business logic from the router but carried transport response construction into the service. `_ServiceResult.to_response()` was intended to keep status-code semantics in the service, but the concrete `JSONResponse` crosses the layer boundary.

**Impact:** `AuthService` cannot be invoked outside a FastAPI context (CLI, unit tests without ASGI). Breaks the service-layer contract established by SVC-3. Any CLI command that calls `AuthService` will require a FastAPI import at CLI layer.

**Fix:** Remove `from fastapi.responses import JSONResponse` from `auth_service.py`. Replace `_ServiceResult.to_response()` return type with a plain `dict` or `ServiceResult(status_code: int, body: dict)` dataclass. Move `JSONResponse(...)` construction to `app/routers/auth.py`. Update `tests/test_auth_service.py` assertions accordingly.

**Verify:** `git grep "from fastapi" app/services/auth_service.py` returns zero results. `pytest tests/test_auth_service.py -q` passes.

**Assigned task:** FIX-H (bundle with CODE-1 fix)

### P1-2 (CODE-3) — `POST /auth/logout` and `POST /auth/refresh` routes not registered

**Symptom:** `AuthService.logout()` and `AuthService.refresh_token()` are fully implemented but `app/routers/auth.py` registers only `POST /auth/token`. The JWT blocklist mechanism is unreachable for external callers.

**Evidence:** `app/routers/auth.py` — single route definition. `app/services/auth_service.py:212` (`logout`), `app/services/auth_service.py:273` (`refresh_token`). ARCH_REPORT — Cycle 11 verdict: DRIFT.

**Root Cause:** SVC-1 scope covered only the login flow; logout and refresh routes were not added to the router.

**Impact:** Token revocation is dead code. Users cannot invalidate tokens before expiry; the blocklist Redis key `jwt:blocklist:{jti}` is never written by the API. Security gap: no token revocation path exists.

**Fix:** Add `POST /auth/logout` and `POST /auth/refresh` routes in `app/routers/auth.py` mirroring the `create_auth_token` pattern. Add tests in `tests/test_endpoints.py` for both routes (authenticated, 401 without token, logout invalidates token, refresh returns new token).

**Verify:** `curl -X POST /auth/logout` with valid JWT returns 200. Subsequent request with same token returns 401. `pytest tests/ -q` passes.

**Assigned task:** FIX-H (bundle with CODE-1 fix)

---

## P2 Issues

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-4 | `auth_ratelimit:{email_hash}` has no tenant prefix; global by design but absent from data-map §3 | `app/middleware/rate_limit.py:129`, `docs/data-map.md §3` | Open — add to data-map |
| CODE-5 | Silent `except Exception:` in `_fetch_embeddings` swallows ANN fallback — no `LOGGER.warning` or `exc_info` | `app/jobs/rca_clusterer.py:276` | Open (carry-forward Cycles 8–10) |
| CODE-6 | `run_eval()` non-async path has no `check_budget()` call — budget bypass via CLI/direct invocation | `eval/runner.py:51-110` | Open (carry-forward as CODE-10/CODE-13) |
| CODE-7 | `run_blocking` raises untyped `data` value — `raise data  # type: ignore[misc]`; no `BaseException` narrowing | `app/utils.py:34` | Open (carry-forward as CODE-9) |
| CODE-8 | `_fetch_raw_texts_admin` uses `gdev_admin` session with no tenant_id assertion guard | `app/jobs/rca_clusterer.py:427-440` | Open (carry-forward as CODE-7/CODE-16) |
| ARCH-5 | `/metrics` JWT exemption: inline comment present (FIX-F) but ADR-004 and ARCHITECTURE.md security section not updated | `app/main.py:371`, `docs/adr/004-observability-stack.md` | Open (partial) |
| ARCH-6 | `GET /clusters/{cluster_id}` returns members via time-window heuristic, not persisted membership | `app/routers/clusters.py:151-175` | Open → CLU-1 Phase 10 |
| ARCH-7 (new) | AuthService imports FastAPI transport type (`JSONResponse`) — same layer violation pattern as old ARCH-7 (agent.py) which SVC-3 fixed | `app/services/auth_service.py:13` | Open — linked to P1-1 (CODE-2) |
| ARCH-8 (new) | `POST /auth/logout` and `POST /auth/refresh` not routed | `app/routers/auth.py` | Open — linked to P1-2 (CODE-3) |
| ARCH-9 (new) | Business logic embedded in `/webhook` and `/approve` route functions in `app/main.py` | `app/main.py:255-366` | Open — deferred Phase 10+ |

---

## P3 Issues

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-9 | No unit test for `_fetch_embeddings` ANN fallback exception branch | `tests/test_rca_clusterer.py` | Open (carry-forward Cycles 8–10) |

---

## Carry-Forward Status

| ID | Sev | Description | Status | Change |
|----|-----|-------------|--------|--------|
| REG-2 | P1 | 14 test failures — root cause: `SET LOCAL` parameterized binding rejected by asyncpg | Open → FIX-H | NEW — stop-ship blocker |
| CODE-2 (now CODE-1) | P0 | `SET LOCAL` parameterized form rejected by asyncpg — root cause of REG-2 | Open → FIX-H | NEW P0 — confirmed root cause |
| CODE-4 | P2 | `auth_ratelimit` key absent from data-map §3 | Open | No change |
| CODE-5 | P2 | Silent exception in `_fetch_embeddings` — no LOGGER.warning | Open | No change — carry-forward Cycles 8–10 |
| CODE-7 (renamed CODE-8) | P2 | `_fetch_raw_texts_admin` no tenant_id assertion | Open | No change — carry-forward |
| CODE-9 (renamed CODE-9) | P2 | `run_blocking` untyped re-raise | Open | No change — carry-forward |
| CODE-10 (renamed CODE-6) | P2 | `run_eval()` non-async path no `check_budget()` | Open | No change — carry-forward |
| CODE-12 / P2-10 | P2 | Module-level `get_settings()` coupling — import-time API key required | Open | No change |
| ARCH-2 | P2 | ADR-002 embedding dim mismatch | CLOSED | DOC-2 resolved: ADR updated to Voyage/1024-dim |
| ARCH-5 | P2 | `/metrics` JWT exemption undocumented | Open (partial) | FIX-F added code comments; ADR-004 + ARCHITECTURE.md update still pending |
| ARCH-6 | P2 | Cluster membership heuristic, not persisted | Open | No change — CLU-1 Phase 10 |
| ARCH-7 | P2 | `agent.py` imports `HTTPException` | CLOSED | SVC-3 resolved: domain exceptions in `app/exceptions.py` |
| ARCH-8 | P2 | Router business logic (auth + eval) | CLOSED | SVC-1 + SVC-2 resolved (partially — see new ARCH-7/ARCH-8 findings) |
| ARCH-9 | P2 | `GET /eval/runs` missing | CLOSED | Implemented; confirmed PASS in ARCH_REPORT Cycle 11 |
| P1-1 | P1 | HS256 vs RS256 conflict | CLOSED | ADR-003 §Consequences documents HS256 as v1 choice; no conflict |
| REG-1 | P1 | 14 test regressions Cycle 8 | CLOSED | FIX-9 resolved; superseded by REG-2 |

---

## Resolved This Cycle

| Finding | Resolution | Evidence |
|---------|------------|----------|
| ARCH-2 | ADR-002 updated to Voyage AI `voyage-3-lite` / VECTOR(1024) | `docs/adr/002-vector-store-design.md` updated by DOC-2 — ARCH_REPORT PASS |
| ARCH-7 | `app/agent.py` has zero `from fastapi import` statements | `app/exceptions.py` domain exceptions; SVC-3 complete — ARCH_REPORT PASS |
| ARCH-8 | Router handlers delegate to AuthService + EvalService | `app/services/auth_service.py`, `app/services/eval_service.py` exist — ARCH_REPORT PASS (partial; new ARCH-7/ARCH-8 findings open) |
| P1-1 | HS256 is the documented v1 choice per ADR-003 | `docs/adr/003-rbac-design.md §Consequences` — no code change needed |

---

## Stop-Ship Decision

**Yes.** 14 test regressions (REG-2) confirmed stop-ship. Root cause is `SET LOCAL` parameterized binding rejected by asyncpg (CODE-1 / P0-1). Repo is NOT green. Phase 10 (CLI-1) must not begin until FIX-H resolves all 14 failures and `pytest tests/ -q` returns 0 failures.

P1 findings (CODE-2: AuthService JSONResponse transport leak; CODE-3: missing logout/refresh routes) are high-severity but not individually stop-ship. They must be bundled into FIX-H or a dedicated FIX-I before CLI-1 ships, since the CLI will invoke `AuthService` directly.

---

_Next: archive this file to `docs/audit/archive/CYCLE11_REVIEW.md` before Cycle 12 begins._
