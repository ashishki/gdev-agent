# Phase 3 Review — T08–T10 (EventStore, Cross-Tenant Fixes, CostLedger)

_Reviewer: Senior Staff Engineer / Architect · Date: 2026-03-04_
_Scope: T08 (Postgres EventStore), P0-1/P0-2/P1-2/P1-3 remediations, T09 (isolation tests), T10 (CostLedger)_

---

## Executive Summary

- **Phase 2 P0/P1 remediations are fully confirmed resolved.** P0-1 (cross-tenant approve bypass), P0-2 (EventStore RLS bypass), P1-2 (sync Redis in RateLimitMiddleware), and P1-3 (double Settings at module load) are all correctly fixed and verified by inspection.
- **No new P0 issues found.** The system is conditionally cleared to proceed to T11.
- **One new P1 found (P1-4):** `_enforce_budget()` silently no-ops when `tenant_id` is `None` or unparseable, allowing webhook calls without a valid tenant_id to bypass the budget guard and make LLM calls unrestricted. This violates the CODEX_PROMPT pipeline safety invariant.
- **P1-1 (HS256 vs RS256) remains unaddressed** — no architecture decision has been made. Must be resolved before any production deployment where other components receive JWTs.
- **P2-7 (reviewer PII) remains open and is broader than originally documented** — raw `reviewer` string appears in three places in `agent.py`, including `AuditLogEntry.approved_by` which is written to Google Sheets.
- **Duplicate config fields** (`anthropic_*_cost_per_1k` and `llm_*_rate_per_1k`) create silent drift risk in tests and configuration.
- **`tasks.md` has documentation drift**: T05, T06, T09 are shown as `pending` but are complete.
- **Stop-ship verdict: NO** — P0 issues resolved; T11 may proceed. Fix P1-4 before enabling budget enforcement in multi-tenant production.

---

## CP1 — Repository Map

| Path | Description |
|------|-------------|
| `app/main.py` | FastAPI entrypoint; lifespan wires all services; 3 routes + auth router |
| `app/agent.py` | AgentService: guard → budget check → LLM → propose → output guard → route/approve |
| `app/store.py` | **[T08]** EventStore: SQLite events + Postgres pipeline persistence with SET LOCAL + _run_blocking |
| `app/cost_ledger.py` | **[T10]** CostLedger: check_budget (raises BudgetExhaustedError) + record (UPSERT) |
| `app/llm_client.py` | LLMClient: Claude tool_use loop (≤5 turns); tenacity retries |
| `app/config.py` | Pydantic Settings with lru_cache; ANTHROPIC_API_KEY required at startup |
| `app/schemas.py` | All Pydantic models; PendingDecision.tenant_id field added (P0-1 fix) |
| `app/db.py` | make_engine(), make_session_factory(), get_db_session() with SET LOCAL |
| `app/approval_store.py` | RedisApprovalStore: get_pending + pop_pending (GETDEL) atomic pop |
| `app/dedup.py` | DedupCache: 24h idempotency by message_id |
| `app/dependencies.py` | require_role(*roles) → FastAPI Depends; raises 403 |
| `app/tenant_registry.py` | TenantRegistry: async Redis cache (TTL 300s) + Postgres fallback |
| `app/secrets_store.py` | WebhookSecretStore: Fernet-decrypt per-tenant HMAC secrets |
| `app/guardrails/output_guard.py` | Secret regex scan + URL allowlist + confidence floor |
| `app/middleware/auth.py` | JWTMiddleware: HS256 verify, blocklist check (async Redis), fail-closed 503 |
| `app/middleware/signature.py` | SignatureMiddleware: ASGI-level HMAC-SHA256, body replay |
| `app/middleware/rate_limit.py` | Per-user rpm+burst (webhook), per-email auth rate limit; async Redis from app.state |
| `app/routers/auth.py` | POST /auth/token: bcrypt check, JWT HS256 issue, RLS tenant context |
| `app/tools/__init__.py` | TOOL_REGISTRY dispatch |
| `app/integrations/` | Linear, Telegram, Sheets API clients |
| `alembic/versions/` | 0001 (16 tables + RLS + roles), 0002 (gdev_admin BYPASSRLS), 0003 (password_hash) |
| `tests/test_isolation.py` | **[T09]** 5 integration tests: DB RLS, EventStore binding, approve 403, admin BYPASSRLS |
| `tests/test_cost_ledger.py` | **[T10]** 3 integration tests: budget 429, UPSERT accumulation, multi-tenant isolation |

---

## CP2 — High-Risk Modules

| Module | Risk |
|--------|------|
| `app/agent.py` | Core pipeline; budget guard + approval cross-tenant check; HTTPException import (layer violation P2-6); reviewer PII (P2-7) |
| `app/cost_ledger.py` | **[T10]** Budget enforcement; RLS-within-join correctness; UPSERT idempotency |
| `app/store.py` | **[T08]** SET LOCAL correctness; _run_blocking thread-bridge spawns 1 thread per request |
| `app/middleware/auth.py` | JWT blocklist; fail-closed 503 on Redis failure; all protected requests pass through |
| `app/middleware/signature.py` | HMAC webhook auth; body consumed and replayed at ASGI level |
| `app/middleware/rate_limit.py` | Uses async Redis from app.state (P1-2 fixed); Retry-After header present |
| `app/routers/auth.py` | JWT issuance; bcrypt; RLS context setup for auth query |
| `app/approval_store.py` | GETDEL atomicity is the sole race guard on approvals |
| `app/dependencies.py` | require_role() is the RBAC enforcement point — any bug affects all protected routes |
| `app/main.py` | `get_settings()` at module load — ANTHROPIC_API_KEY required at import time |
| `app/db.py` | SET LOCAL is the RLS boundary; skip means cross-tenant data exposure |
| `app/schemas.py` | PendingDecision.tenant_id — cross-tenant check depends on this field |
| `app/config.py` | Duplicate cost fields; lru_cache singleton; jwt_secret weak default |
| `alembic/versions/0001_initial_schema.py` | RLS policy definitions; tenant isolation depends on these |
| `app/guardrails/output_guard.py` | Output secret scan + URL allowlist + confidence floor |

---

## CP3 — Documentation Status

| Document | Status | Notes |
|----------|--------|-------|
| `docs/CODEX_PROMPT.md` | Outdated (v2.6) | Needs v2.7 with Phase 3 findings |
| `docs/tasks.md` | **Drift: T05, T06, T09 show `pending` but are done** | Multiple task statuses incorrect |
| `docs/PHASE2_REVIEW.md` | Accurate | P0 findings all confirmed resolved |
| `docs/adr/003-rbac-design.md` | **Outdated** | States RS256 + JWKS; implementation is HS256 |
| `docs/data-map.md §3` | **Outdated** | Redis keys show tenant-prefixed patterns; code uses flat keys |
| `docs/N8N.md §8.8` | **Outdated** | References `REVIEW_NOTES.md §5.12` (file does not exist) |
| `docs/dev-standards.md` | Accurate | Violations documented here |
| `docs/PHASE1_REVIEW.md` | Accurate | All P1 issues resolved |

---

## Phase 2 Remediation Verification

### P0-1 · Cross-tenant /approve isolation ✅ CONFIRMED FIXED

**Evidence (`app/agent.py:242-256`):**
```python
def approve(self, request: ApproveRequest, jwt_tenant_id: str | None = None) -> ApproveResponse:
    pending = self.approval_store.get_pending(request.pending_id)
    if not pending:
        raise HTTPException(status_code=404, detail="pending_id not found")
    if jwt_tenant_id is None or str(pending.tenant_id) != str(jwt_tenant_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    pending = self.approval_store.pop_pending(request.pending_id)   # pop only after auth check
```

**Evidence (`app/main.py:214-219`):**
```python
jwt_tenant_id = None
if hasattr(request, "state"):
    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id is not None:
        jwt_tenant_id = str(tenant_id)
return app.state.agent.approve(payload, jwt_tenant_id=jwt_tenant_id)
```

Sequence is: `get_pending` → validate tenant → `pop_pending`. The entry is not consumed before the authorization check. HTTP 403 returned on mismatch as required. If `jwt_tenant_id` is `None` (webhook caller without JWT), fails closed with 403. ✅

**Test coverage:** `tests/test_isolation.py:test_approve_cross_tenant_is_forbidden_and_pending_remains` — asserts HTTP 403 and verifies pending entry remains unconsumed. ✅

---

### P0-2 · EventStore RLS bypass ✅ CONFIRMED FIXED

**Evidence (`app/store.py:127-132`):**
```python
async with self._db_session_factory() as session:
    async with session.begin():
        await session.execute(
            text("SET LOCAL app.current_tenant_id = :tid"),
            {"tid": str(payload_tenant_id)},
        )
        ticket_row = await session.execute(...)  # SET LOCAL precedes all INSERTs
```

`SET LOCAL` is the first operation inside `session.begin()`. All five INSERTs follow within the same transaction. The tenant_id consistency check (`payload_tenant_id != audit_tenant_id` raises ValueError at lines 120-123) guards before the session opens. ✅

**Test coverage:** `tests/test_isolation.py:test_event_store_binds_all_rows_to_payload_tenant` — 5 tables verified for correct tenant binding via gdev_app role. ✅

---

### P1-2 · RateLimitMiddleware async Redis ✅ CONFIRMED FIXED

**Evidence (`app/middleware/rate_limit.py:45,61-67`):**
```python
redis_client = self.redis or getattr(request.app.state, "jwt_blocklist_redis", None)
...
minute_count = int(await redis_client.incr(minute_key))   # ← awaited
await redis_client.expire(minute_key, 60)                  # ← awaited
burst_count = int(await redis_client.incr(burst_key))      # ← awaited
await redis_client.expire(burst_key, 10)                   # ← awaited
```

The async client from `app.state.jwt_blocklist_redis` is used at request time (not at module load). All Redis calls are awaited. ✅

---

### P1-3 · Double Settings at module load ✅ CONFIRMED FIXED

**Evidence (`app/main.py:148,153-158`):**
```python
_middleware_settings = get_settings()  # lru_cache singleton — same instance as lifespan

app.add_middleware(JWTMiddleware, settings=_middleware_settings)
app.add_middleware(RateLimitMiddleware, settings=_middleware_settings, redis_client=None)
app.add_middleware(SignatureMiddleware, settings=_middleware_settings)
```

Only one Settings instance created (via lru_cache). No `redis.from_url()` at module load — `redis_client=None` passed and resolved at request time from `app.state`. ✅

**Note (new finding):** `get_settings()` at `main.py:148` is called at **module load time**, before the lifespan runs. This means `ANTHROPIC_API_KEY` must be present in the environment at import time. This is intentional per the P1-3 fix notes, but creates a fragility: tests that import `app.main` without setting `ANTHROPIC_API_KEY` will fail with `ValueError`. Current test suite handles this (88 pass), but future test files must set this env var before importing `app.main`. Tracked as P2-10.

---

## Critical Issues (P0)

_No new P0 issues found in T08–T10._

---

## Major Issues (P1)

---

### P1-1 · ADR-003 mandates RS256; implementation uses HS256 — STILL OPEN

**Symptom:**
ADR-003 specifies RS256 asymmetric JWT signing with a JWKS endpoint. All code uses HS256.

**Evidence:**
```python
# app/config.py:46
jwt_algorithm: str = "HS256"
# docs/adr/003-rbac-design.md:53
# "JWT signed with RS256 (asymmetric). Public key published at /auth/jwks.json."
```

**Impact / Risk:**
With HS256, any component holding `JWT_SECRET` can forge tokens for any tenant and role. In a multi-component deployment (n8n, worker processes, external integrations), the signing key must be shared across all components. The default `jwt_secret = "dev-jwt-secret-must-be-at-least-32b"` is 34 bytes — no startup warning fires, so this weak default can reach production unnoticed.

**Location:** `app/config.py:45-46`, `app/middleware/auth.py:43-47`, `app/routers/auth.py`, `docs/adr/003-rbac-design.md`

**Required Decision:** Accept HS256 for v1 (update ADR-003, enforce 32-byte minimum via RuntimeError not warning) OR implement RS256. No implementation should proceed until this decision is documented.

**Confidence:** High

---

### P1-4 · `_enforce_budget()` silently no-ops when `tenant_id` is None — NEW

**Symptom:**
Any webhook request where `tenant_id` is absent or unparseable in the payload silently bypasses the budget guard and proceeds to make LLM calls without any spending check.

**Evidence:**
```python
# app/agent.py:470-488
def _enforce_budget(self, tenant_id: str | None) -> None:
    tenant_uuid = self._tenant_uuid(tenant_id)
    session_factory = getattr(self.store, "_db_session_factory", None)
    if tenant_uuid is None or session_factory is None:
        return   # ← silent no-op; LLM call proceeds unrestricted
    ...
```

**Root Cause Hypothesis:**
The no-op guard was added to handle cases where the EventStore has no DB session factory (unit test scenarios without Postgres). However, it also silently bypasses the budget check for webhook payloads that arrive without a valid `tenant_id`. Since the webhook endpoint does not require a JWT (HMAC only), `request.state.tenant_id` is not set, and `payload.tenant_id` may be None.

**Impact / Risk:**
CODEX_PROMPT §AGENT PIPELINE SAFETY mandates: "Budget check (`CostLedger.check_budget()`) must run BEFORE every LLM call." A webhook without `tenant_id` violates this invariant, enabling unlimited LLM usage for that request. The HMAC auth guard limits this to requests from known tenants, but a misconfigured n8n workflow omitting `tenant_id` could incur unbounded cost.

**Location:** `app/agent.py:470-488`, `app/main.py:169-199`

**Proposed Fix (high level):**
In the webhook route handler (`main.py`), validate that `payload.tenant_id` is non-None after the JWT/HMAC context is resolved. If still None, return HTTP 400 ("tenant_id required"). This shifts the guard to the HTTP layer rather than silently deferring it inside `_enforce_budget`. Alternatively, raise `ValueError` in `_enforce_budget` when `tenant_uuid is None` and handle it as 400 at the route.

**Verification Steps:**
- Test: send webhook without `tenant_id` → assert HTTP 400 (not 200).
- Test: send webhook with invalid `tenant_id` string → assert HTTP 400.
- Test: send webhook with valid `tenant_id` and exhausted budget → assert HTTP 429.

**Confidence:** High

---

## Major Issues (P2)

---

### P2-1 · Redis keys lack tenant namespace — STILL OPEN (doc drift only)

**Status:** Implementation confirmed as flat-keyed. Documentation update deferred to Phase 5 per earlier decision. `data-map.md §3` still shows tenant-prefixed pattern.

**Required:** `data-map.md §3` must document the current flat-key implementation with a note about Phase 5 hardening.

---

### P2-3 · `kb_base_url` defaults to `kb.example.com` not in URL_ALLOWLIST — STILL OPEN

No change since Phase 2. `config.py:25` still defaults to `DEFAULT_KB_BASE_URL = "https://kb.example.com"`. `.env.example` still does not document this as required. FAQ URLs silently stripped by output guard in any deployment using the default.

---

### P2-5 · `REVIEW_NOTES.md §5.12` reference in N8N.md — STILL OPEN

`docs/N8N.md:477` still references `REVIEW_NOTES.md §5.12`. The file does not exist.

---

### P2-6 · `AgentService` imports `HTTPException` from fastapi — STILL OPEN

`app/agent.py:15`: `from fastapi import HTTPException`. AgentService raises FastAPI exceptions directly. Layer violation as per dev-standards §3.2.

---

### P2-7 · Reviewer PII stored raw — STILL OPEN, SCOPE EXPANDED

**Original scope:** Two `store.log_event()` calls in `approve()`.

**Additional finding (Phase 3):** `AuditLogEntry.approved_by` at `app/agent.py:299` is also set to `request.reviewer` raw. This entry is written to Google Sheets via `_append_audit_async()`. The `AuditLogEntry` schema (`app/schemas.py:137`) types `approved_by: str | None = None` without any hashing enforcement.

**All three affected sites:**
```python
# app/agent.py:264 — pending_rejected event
"reviewer": request.reviewer,  # raw PII

# app/agent.py:282 — pending_approved event
"reviewer": request.reviewer,  # raw PII

# app/agent.py:299 — AuditLogEntry → Google Sheets
approved_by=request.reviewer,  # raw PII (Telegram user ID)
```

**Fix:** Hash with `hashlib.sha256((request.reviewer or "").encode()).hexdigest()[:16]` at all three sites. Update `data-map.md §2` `audit_log.approved_by` comment.

---

### P2-8 · Duplicate cost config fields — NEW

**Symptom:**
`app/config.py` defines two sets of cost rate fields:
- `anthropic_input_cost_per_1k: float = 0.003` (line 26) — legacy float
- `anthropic_output_cost_per_1k: float = 0.015` (line 27) — legacy float
- `llm_input_rate_per_1k: Decimal = Decimal("0.003")` (line 28) — T10 Decimal
- `llm_output_rate_per_1k: Decimal = Decimal("0.015")` (line 29) — T10 Decimal

**Evidence of divergence:** `tests/test_agent.py:80-81` sets `anthropic_input_cost_per_1k=0.003` and `anthropic_output_cost_per_1k=0.015` expecting them to affect cost calculation. But `app/agent.py:435-437` uses only `llm_input_rate_per_1k` and `llm_output_rate_per_1k`. The test's cost assertion at line 98 uses `anthropic_input_cost_per_1k` — but since both happen to have the same numeric value, the test passes. If the `anthropic_*` fields were changed to different values, the test would still pass (calculating with the wrong rate).

**Impact / Risk:** Configuration drift — an operator who sets `ANTHROPIC_INPUT_COST_PER_1K` in `.env` expecting it to control cost estimation will find it has no effect. The `llm_*_rate_per_1k` fields control actual behavior.

**Proposed Fix:** Deprecate `anthropic_input_cost_per_1k` and `anthropic_output_cost_per_1k`. Update `test_agent.py:80-81` to use `llm_input_rate_per_1k` / `llm_output_rate_per_1k`.

---

### P2-9 · `_run_blocking` duplicated across `store.py` and `agent.py` — NEW

`app/store.py:83-104` and `app/agent.py:447-468` contain an identical `_run_blocking` method. Code is duplicated with no shared utility. If one is fixed (e.g., for error handling or thread pool limits), the other may not be updated. Under load, 2–3 threads are spawned per webhook call (one from `persist_pipeline_run`, one from `_enforce_budget`, one from `_record_cost_best_effort`), compounding P2-2 (thread churn).

**Proposed Fix:** Extract to `app/utils.py` or `app/async_utils.py`. Tracked as P3-level cleanup.

---

### P2-10 · `get_settings()` at module load requires ANTHROPIC_API_KEY at import time — NEW

**Symptom:**
`app/main.py:148` calls `get_settings()` at module load time (before lifespan). `get_settings()` raises `ValueError("ANTHROPIC_API_KEY is required")` if the key is absent. Any test that imports `app.main` without first setting `ANTHROPIC_API_KEY` in the environment will fail.

**Current state:** The 88-test suite handles this (ANTHROPIC_API_KEY is set in test fixtures). However, new test files that naively `import app.main` before patching `ANTHROPIC_API_KEY` will fail with a `ValueError` before any test assertion runs. Conftest.py must be consulted before writing any new test that imports from `app.main`.

**Proposed Fix (doc only):** Document in `docs/CODEX_PROMPT.md` that all test files touching `app.main` must set `ANTHROPIC_API_KEY` via `monkeypatch.setenv` or a conftest fixture before the first import.

---

### P2-11 · SQL DDL string interpolation in integration test helpers — NEW

**Evidence (`tests/test_isolation.py:121-124`):**
```python
await conn.execute(
    text(f"ALTER ROLE {role} LOGIN PASSWORD :password"),  # ← role is string-formatted
    {"password": password},
)
```

The `role` variable is a hardcoded constant (`"gdev_app"` or `"gdev_admin"`), so this is not exploitable. However, it contradicts the project-wide rule "all SQL must be parameterized" and sets a precedent that could be copied into application code. Same pattern in `test_cost_ledger.py:124-126`.

**Note:** PostgreSQL DDL (`ALTER ROLE`) does not support parameterized role identifiers, so this cannot be easily fixed with `text()` params. The current usage is safe because the role names are hardcoded. A comment explaining why this DDL string format is intentional would remove the ambiguity.

---

### P2-12 · `tasks.md` status drift for T05, T06, T09 — NEW (doc only)

**Evidence:**
```
# tasks.md:279  T05 Status: pending   ← DONE
# tasks.md:355  T06 Status: pending   ← DONE
# tasks.md:494  T09 Status: pending   ← DONE
```

All three tasks are confirmed complete per CODEX_PROMPT.md and the codebase. The task statuses were not updated when those tasks were merged.

---

## Improvements (P3)

---

### P3-5 · `raw_text` stored in Postgres `tickets` — clarify intent

`store.py:149` stores `"raw_text": payload.text` (the player's full message) in the `tickets` table. This is correct per spec — it's the primary input for RCA and embedding. However, `raw_text` is High-PII per `data-map.md §1`. A clarifying comment in `store.py` would prevent future developers from treating this as a redaction oversight.

---

### P3-6 · Thread pool pressure from multiple `_run_blocking` calls per request

Per webhook call, up to 3 threads are spawned:
1. `_enforce_budget()` → `_run_blocking()` (budget check)
2. `_record_cost_best_effort()` → `_run_blocking()` (cost record)
3. `store.persist_pipeline_run()` → `EventStore._run_blocking()` (DB write)

Under 100 RPM, this creates 300 threads/minute in addition to FastAPI's thread pool. Tracked as P2-2 (EventStore thread-bridge). Converting `/webhook` to `async def` and using `asyncio.create_task()` eliminates thread spawning entirely. Address in T11 or a dedicated refactor task.

---

### P3-7 · `cost_usd` type inconsistency: `float` vs `Decimal`

`_estimate_llm_cost_usd()` returns `float`. It is then converted `Decimal(str(cost_usd))` in `_record_cost_best_effort`. The float-to-string-to-Decimal path introduces floating-point rounding artifacts (e.g., 0.0015 USD may store as 0.001500000000000000... in Decimal). For accounting purposes, `Decimal` arithmetic throughout would be more correct. `AuditLogEntry.cost_usd: float` should become `Decimal`, though this is a minor concern given the small values involved.

---

## Architecture Consistency Check

| Spec/ADR | Doc Says | Implementation | Gap |
|---|---|---|---|
| ADR-003 | RS256 + JWKS endpoint | HS256, no JWKS | P1-1 (open) |
| spec.md §4 / data-map.md §3 | `{tenant_id}:` Redis prefix | Flat namespace | P2-1 (open, doc-only deferred) |
| CODEX_PROMPT §AGENT PIPELINE SAFETY | Budget check before EVERY LLM call | Skipped if tenant_id=None | P1-4 (new) |
| dev-standards §3.2 | Services not importing FastAPI | `agent.py` imports HTTPException | P2-6 (open) |
| dev-standards §PII | reviewer stored hashed | Raw reviewer in 3 log/audit sites | P2-7 (open) |
| data-map.md §2 | `audit_log.approved_by` = hash | Raw reviewer in AuditLogEntry | P2-7/P2-12 (open) |
| config.py | Single authoritative cost rate | Dual fields (float + Decimal) | P2-8 (new) |
| T09 in tasks.md | Status: pending | Complete (tests exist) | doc drift P2-12 |

---

## Security Review

| Area | Finding | Severity |
|------|---------|----------|
| Approval cross-tenant isolation | ✅ FIXED (P0-1) | Resolved |
| EventStore RLS bypass | ✅ FIXED (P0-2) | Resolved |
| Budget guard bypass on None tenant_id | Budget can be skipped | P1-4 |
| JWT algorithm | HS256 vs ADR RS256 | P1-1 (open) |
| Reviewer PII in logs and Sheets | 3 raw storage sites | P2-7 |
| RateLimitMiddleware | ✅ Async; Retry-After header present | OK |
| JWT blocklist | ✅ Fail-closed 503 on Redis failure | OK |
| SQL parameterization | ✅ All application queries parameterized | OK |
| HMAC webhook auth | ✅ Per-tenant, Fernet-encrypted | OK |
| bcrypt timing | ✅ Dummy hash prevents user enumeration | OK |
| Output guard | ✅ Secret patterns + URL allowlist + confidence floor | OK |
| APPROVE_SECRET enforcement | Warning only (P3-1) | P3 |

---

## Testing Review

| Test | Coverage | Status |
|------|----------|--------|
| `test_isolation.py` — 5 integration tests | DB RLS read/write, EventStore binding, approve 403, gdev_admin | ✅ Correct |
| `test_cost_ledger.py` — 3 integration tests | Budget 429, UPSERT accumulation, multi-tenant isolation | ✅ Correct |
| `test_agent.py:test_cost_ledger_record_failure_is_logged_and_non_fatal` | Non-fatal record failure | ✅ Correct |
| Budget bypass when tenant_id=None | Unverified | ❌ Missing |
| approve() with jwt_tenant_id=None | Untested | ❌ Missing |
| Reviewer hashing (P2-7) | No assertion that raw reviewer is absent from events | ❌ Missing |
| Duplicate config fields (P2-8) | test_agent.py:98 uses anthropic_* (wrong field) | ⚠ Misleading |
| SET LOCAL in _enforce_budget and _record_cost_best_effort | Implicit (uses same session_factory pattern) | ✅ Correct |

**Baseline confirmed: 88 pass, 12 skipped. No regressions from T08–T10.**

---

## Documentation Accuracy Review

| Document | Finding |
|----------|---------|
| `docs/tasks.md` | T05, T06, T09 show `Status: pending` — all three are done. Fix required. |
| `docs/CODEX_PROMPT.md` | v2.6; needs v2.7 with Phase 3 findings |
| `docs/adr/003-rbac-design.md` | RS256 mandated; implementation is HS256. Decision deferred. ADR must be updated once decided. |
| `docs/data-map.md §3` | Shows tenant-prefixed Redis keys; code uses flat keys. Note needed. |
| `docs/N8N.md §8.8` | Dangling `REVIEW_NOTES.md §5.12` reference — file does not exist. |
| `docs/PHASE2_REVIEW.md` | Accurate — all P0/P1 findings in it are now resolved. No update needed. |

---

## Stop-Ship Decision

**STOP-SHIP: NO**

All Phase 2 P0 issues are confirmed fixed. No new P0 issues were introduced in T08–T10. T11 may proceed.

**Conditions for production multi-tenant deployment:**
1. P1-4 must be fixed (budget bypass on None tenant_id) before enabling budget enforcement.
2. P1-1 requires an architecture decision (HS256 formally accepted or RS256 implemented) before external token consumers are added.
3. P2-7 (reviewer PII) should be addressed before any real user data flows through the approve path.
