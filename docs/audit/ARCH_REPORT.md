---
# ARCH_REPORT — Cycle 11
_Date: 2026-03-18_

## Component Verdicts

| Component | Verdict | Note |
|-----------|---------|------|
| `app/agent.py` — AgentService | PASS | No FastAPI import (P2-6 resolved). Domain exceptions (`AgentError`, `BudgetError`, `ValidationError`) from `app/exceptions.py` used throughout. Business logic correctly separated from transport. |
| `app/services/auth_service.py` — AuthService | DRIFT | Imports `fastapi.responses.JSONResponse` (line 13); `_ServiceResult.to_response()` constructs a `JSONResponse` inside the service layer — transport type leaks across layer boundary. SVC-1 partially unmet. |
| `app/services/eval_service.py` — EvalService | PASS | No FastAPI imports. Clean service contract. Budget check, DB writes, and background task dispatch all in service layer. |
| `app/routers/auth.py` — auth router | DRIFT | Exposes only `POST /auth/token` (login). `logout()` and `refresh_token()` methods exist in `AuthService` but no corresponding router endpoints are registered. Dead service code or missing routes (ARCH-8). |
| `app/routers/eval.py` — eval router | PASS | Thin handlers; all business logic delegated to `EvalService`. Error translation at router boundary is correct pattern. |
| `app/routers/clusters.py` — clusters router | DRIFT | `GET /clusters/{cluster_id}` contains inline SQL with time-window heuristic membership query (lines 151–175) — business logic in router layer. ARCH-6 carry-forward; CLU-1 not yet implemented. |
| `app/main.py` — `/webhook` and `/approve` handlers | DRIFT | Both handlers contain business logic: tenant_id resolution, UUID validation, dedup cache access, OTel span management, HMAC `X-Approve-Secret` check. Not thin handler shells. Pre-dates Phase 9 service-layer extraction (ARCH-9). |
| `app/llm_client.py` — LLMClient | PASS | No FastAPI imports. Tool-use loop capped at default `max_turns=5` (line 186, enforced at line 199). |
| `app/guardrails/output_guard.py` — OutputGuard | PASS | Clean; no transport imports. |
| `app/middleware/` — auth, rate_limit, signature | PASS | FastAPI/Starlette imports are correct at the middleware layer. |
| `app/exceptions.py` — domain exceptions | PASS | No transport imports. `AgentError` carries `status_code` metadata; mapped to HTTP responses in `main.py` exception handler — correct pattern. |
| `app/jobs/rca_clusterer.py` — RCA Clusterer | DRIFT | `_fetch_embeddings` swallows exception silently with no warning log (CODE-5). `_fetch_raw_texts_admin` uses `gdev_admin` session without `tenant_id` assertion guard (CODE-7). Both carry-forward from Cycle 10. |
| `eval/runner.py` — EvalRunner | DRIFT | Non-async `run_eval()` path skips `check_budget()` call — budget bypass for CLI or direct invocation (CODE-10). |
| `app/utils.py` — run_blocking | DRIFT | `raise data  # type: ignore[misc]` — untyped re-raise; no `BaseException` narrowing (CODE-9). |

---

## ADR Compliance

| ADR | Verdict | Note |
|-----|---------|------|
| ADR-001 — PostgreSQL + RLS + Redis cache | PASS | Postgres is primary store. Alembic migrations 0001/0002 implement 16-table schema with RLS policies and `gdev_app`/`gdev_admin` roles. Redis retained for TTL-based ephemeral keys only. Google Sheets retained as optional export per ADR intent. |
| ADR-002 — pgvector conditional (Voyage AI) | PASS | `ticket_embeddings.embedding VECTOR(1024)` in schema; TEXT fallback in migration; HNSW index specified in data-map. ADR updated in DOC-2 to record Voyage AI (`voyage-3-lite`) replacing the original OpenAI `text-embedding-3-small` reference. Implementation, config (`app/config.py:29`), and ADR are now consistent. ARCH-2 is closed. |
| ADR-003 — RBAC: HS256 | PASS | ADR-003 §Consequences explicitly documents HS256 as the v1 choice and describes the RS256 migration path. Code uses HS256 consistently. The P1-1 finding in MEMORY.md ("RS256 mandated, HS256 implemented") is a misread; the ADR accepts HS256 for v1. P1-1 should be closed. |
| ADR-004 — OTel spans + Prometheus in new services | PASS | `AuthService` and `EvalService` both include OTel `TRACER` (with noop fallback) and Prometheus `Counter`/`Histogram` metrics. Span naming follows `service.auth.*` / `service.eval.*` convention consistent with ADR-004 trace schema. |
| ADR-005 — Claude tool_use loop ≤ 5 turns | PASS | `LLMClient` defaults `max_turns=5` (line 186); loop enforces limit (line 199). APScheduler in-process for RCA/cost jobs per ADR-005 §v1 Implementation. Eval on-demand via `POST /eval/run`. Migration trigger criteria not yet reached. |

---

## Architecture Findings

### ARCH-7 [P2] — AuthService imports FastAPI transport type
Symptom: `AuthService._ServiceResult.to_response()` constructs a `JSONResponse` inside the service layer.
Evidence: `app/services/auth_service.py:13` — `from fastapi.responses import JSONResponse`; `app/services/auth_service.py:87` — `return JSONResponse(...)`.
Root cause: SVC-1 extracted business logic from the router but carried transport response construction into the service. `_ServiceResult` was intended to keep status-code semantics in the service, but the concrete `JSONResponse` type crosses the layer boundary.
Impact: Service cannot be used outside a FastAPI context (CLI, unit tests without ASGI). Tests for `AuthService` implicitly depend on FastAPI being importable.
Fix: Replace `JSONResponse` return in `to_response()` with a plain dict or a `ServiceResult(status_code, payload_dict)` dataclass. Move `JSONResponse(...)` construction to the router. Remove `fastapi` import from `auth_service.py`.

### ARCH-8 [P2] — `POST /auth/logout` and `POST /auth/refresh` not routed
Symptom: `AuthService` implements `logout()` and `refresh_token()` but `app/routers/auth.py` only registers `POST /auth/token`.
Evidence: `app/routers/auth.py` — single route definition. `app/services/auth_service.py:212,273` — both methods fully implemented.
Root cause: SVC-1 scope covered only the login flow; logout and refresh routes were not added to the router.
Impact: Token revocation (`logout`) and refresh are unreachable via the API. The JWT blocklist mechanism is dead code for external callers; users cannot invalidate tokens before expiry.
Fix: Add `POST /auth/logout` and `POST /auth/refresh` routes in `app/routers/auth.py` mirroring the `create_auth_token` pattern. Update ARCHITECTURE.md §2.1 and spec.md §8 API surface table.

### ARCH-9 [P2] — Business logic embedded in `/webhook` and `/approve` route functions
Symptom: `POST /webhook` in `app/main.py` contains tenant_id resolution, UUID validation, dedup cache interaction, and OTel span management. `POST /approve` contains `X-Approve-Secret` HMAC check logic inline.
Evidence: `app/main.py:255–346` (webhook), `app/main.py:349–366` (approve).
Root cause: These handlers pre-date the service-layer pattern introduced in Phase 9. SVC-1/SVC-2/SVC-3 extracted auth and eval but did not extract webhook/approve flows.
Impact: Inconsistent layer discipline across the codebase; webhook/approve handlers are harder to test in isolation. Not blocking for CLI-1 since CLI will invoke services directly, not through these routes.
Fix: Phase 10+ — extract webhook routing logic into `AgentService` or a new `WebhookService`; move `X-Approve-Secret` check into `AgentService.approve()` or a dedicated middleware. Lower priority than ARCH-7/ARCH-8.

### ARCH-6 [P2] — `GET /clusters/{cluster_id}` returns members via time-window heuristic (carry-forward)
Symptom: Member tickets derived by querying `ticket_embeddings` within `first_seen`/`last_seen` timestamps, not by persisted cluster membership records.
Evidence: `app/routers/clusters.py:151–175`.
Root cause: `rca_cluster_members` table and Alembic migration 0003 not yet implemented. CLU-1 deferred to Phase 10.
Impact: Cluster membership is approximate and unstable; tickets added or removed from the time window after cluster creation change membership silently. Business reports on cluster composition are unreliable.
Fix: CLU-1 (Phase 10) — add `rca_cluster_members` table with migration 0003; write membership at cluster creation in `rca_clusterer.py`; replace heuristic query with direct membership join in `clusters.py`. Verify no integration tests depend on heuristic behaviour before replacing.

### ARCH-5 [P2] — `/metrics` JWT exemption absent from ADR and ARCHITECTURE.md (carry-forward, partially mitigated)
Symptom: `GET /metrics` is exempt from `JWTMiddleware`; the security rationale (Prometheus scrape; network-layer restriction) is present only in an inline code comment.
Evidence: `app/main.py:371` — inline comment added by FIX-F. No ADR or ARCHITECTURE.md security section documents this policy.
Root cause: FIX-F mitigated the code-level gap but did not add a doc-level decision record.
Impact: If network restriction is removed or misconfigured, metrics expose tenant_id hashes and operational counters without authentication. No written policy means reviewers cannot verify the assumption holds.
Fix: Add a paragraph to ARCHITECTURE.md §Security (or §Observability) stating that `/metrics` relies on network-layer access control; add a note to ADR-004 §Consequences. Low effort; no code change needed.

---

## CLI-1 Design Assessment

CLI-1 (Typer admin CLI at `scripts/cli.py`) is a Phase 10 start task. Architecture assessment:

- **Service layer reuse**: The CLI should invoke `app/services/` (AuthService, EvalService) and domain objects (CostLedger, TenantRegistry) directly — not by making HTTP calls to the running API. This avoids coupling the CLI to the transport layer and allows offline admin operations.
- **DB access**: CLI must initialise an `AsyncEngine` and `AsyncSession` factory (via `app/db.make_engine()` and `app/db.make_session_factory()`). Pattern already established in `scripts/seed_db.py`.
- **Budget bypass risk**: `eval/runner.py` non-async path has no `check_budget()` call (CODE-10). Any CLI `rca run` or `eval run` command that invokes `run_eval()` directly is subject to the same bypass. CODE-10 must be fixed before or alongside CLI-1.
- **No new ADR required** for CLI-1 as long as it uses the existing service layer and DB stack. If CLI introduces a new execution model (e.g., Celery task dispatch, direct RCA trigger bypassing APScheduler), a new ADR is warranted.

## CLU-1 Design Assessment

CLU-1 introduces `rca_cluster_members` table and migration 0003:

- **RLS placement**: The new table must have an RLS policy `tenant_id = current_setting('app.current_tenant_id')::UUID` consistent with all other tenant-scoped tables in migration 0001. The `gdev_app` user must have `SELECT/INSERT` on the table; `gdev_admin` has `BYPASSRLS`.
- **Clusterer admin session write pattern**: `rca_clusterer.py` uses `gdev_admin` for reads (`_fetch_raw_texts_admin`). Writes to `rca_cluster_members` should use the `gdev_app` session with `SET LOCAL app.current_tenant_id` set to the tenant being clustered — matching the write pattern in `AgentService` and `EvalService`. Using `gdev_admin` for writes is acceptable but removes the RLS defence-in-depth layer; document the choice explicitly if that path is taken.
- **Heuristic callers**: After CLU-1, audit `app/routers/clusters.py` and any integration tests for remaining callers of the time-window heuristic. Replace all before removing the heuristic code path.

---

## Doc Patches Needed

| File | Section | Change |
|------|---------|--------|
| `docs/ARCHITECTURE.md` | §2.1 Component Status | Mark `POST /auth/logout` and `POST /auth/refresh` as missing routes; update auth router description (ARCH-8) |
| `docs/ARCHITECTURE.md` | §Security or §Observability | Document `/metrics` JWT exemption and network-layer access control assumption (ARCH-5) |
| `docs/spec.md` | §8 API Surface | Add `POST /auth/logout` and `POST /auth/refresh` rows to the API table (ARCH-8) |
| `docs/CODEX_PROMPT.md` | Open findings | Close ARCH-2 (resolved by DOC-2); close P1-1 (HS256 is the documented v1 choice per ADR-003, not a violation) |
| `docs/adr/003-rbac-design.md` | (no change needed) | ADR already documents HS256 as v1 choice; P1-1 in MEMORY.md should be closed as a misread |
| `docs/adr/004-observability-stack.md` | §Consequences | Add note that `/metrics` endpoint relies on network-layer restriction; no JWT auth by design (ARCH-5) |

---

_ARCH_REPORT.md written. Run PROMPT_2_CODE.md._
