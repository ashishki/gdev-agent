# Phase 2 Review — T05–T07 (Auth, JWT, RBAC, Role Enforcement)

_Reviewer: Senior Staff Engineer / Architect · Date: 2026-03-04_
_Scope: T05 (JWT middleware + tenant context), T06 (RBAC + /auth/token), T06B (auth blockers),_
_T07 (role enforcement on all endpoints)_

---

## Executive Summary

- **Phase 1 legacy issues**: 5 of 7 issues from MEMORY are RESOLVED in the delivered code. Two remain open (double Settings/Redis at module load; hardcoded `kb.example.com`). Three previously "open" issues (JsonFormatter, rate_limit_burst, Retry-After, dead GETDEL code, deprecated `get_event_loop`) are fully closed.
- **Two new P0 security defects**: (1) `/approve` endpoint has NO cross-tenant tenant_id validation — a `support_agent` from Tenant A can approve a pending action belonging to Tenant B if they obtain a valid `pending_id`. (2) `EventStore._persist_pipeline_run_async()` opens a DB session without `SET LOCAL app.current_tenant_id`, causing all INSERTs to RLS-protected tables to fail in production under the `gdev_app` role.
- **ADR-003 architectural deviation (P1)**: ADR-003 mandates RS256 asymmetric JWT signing; implementation uses HS256. No `/auth/jwks.json` endpoint exists.
- **Async correctness regression (P1)**: `RateLimitMiddleware.dispatch()` is `async def` but calls synchronous Redis (`self.redis.incr()`, `self.redis.expire()`) — blocks the uvicorn event loop for every rate-limited request. The same pattern was fixed for `TenantRegistry` in T00A but introduced again here.
- **Observability layer is entirely absent**: dev-standards §7 mandates OTel spans, Prometheus counters, and Prometheus histograms on every service method. No `app/metrics.py` exists; no tracer is wired. This is a gap across the full codebase.
- **Redis keys are not tenant-namespaced**: `spec.md §4` and `data-map.md §3` both mandate `{tenant_id}:` prefix; dedup, approval, and rate-limit keys all use flat namespaces. Cross-tenant collisions are possible in a multi-tenant deployment.
- **Stop-ship verdict: YES** — P0-1 (cross-tenant approval bypass) is a security breach in multi-tenant operation. Must be fixed before any multi-tenant deployment.

---

## CP1 — Repository Map

| Path | Description |
|------|-------------|
| `app/main.py` | FastAPI entrypoint; lifespan; middleware stack registration; route definitions |
| `app/agent.py` | AgentService: input guard → LLM → propose → output guard → route/approve |
| `app/llm_client.py` | LLMClient: Claude tool_use loop (≤5 turns); tenacity retries on 5xx |
| `app/config.py` | Pydantic Settings with `lru_cache`; validates ANTHROPIC_API_KEY |
| `app/schemas.py` | All Pydantic models (WebhookRequest, ClassificationResult, PendingDecision, etc.) |
| `app/db.py` | `make_engine()`, `make_session_factory()`, `get_db_session()` with SET LOCAL |
| `app/store.py` | EventStore: SQLite event log + Postgres pipeline run persistence (thread-bridge pattern) |
| `app/approval_store.py` | RedisApprovalStore: `GETDEL`-based atomic pop; TTL check |
| `app/dedup.py` | DedupCache: 24h idempotency by `message_id` |
| `app/dependencies.py` | `require_role(*roles)` → FastAPI Depends; raises 403 |
| `app/tenant_registry.py` | TenantRegistry: async Redis cache (TTL 300s) + Postgres fallback |
| `app/secrets_store.py` | WebhookSecretStore: Fernet-decrypt per-tenant HMAC secrets from Postgres |
| `app/logging.py` | `JsonFormatter`, `configure_logging()`, `REQUEST_ID` contextvar |
| `app/guardrails/output_guard.py` | Secret regex scan + URL allowlist + confidence floor |
| `app/middleware/auth.py` | JWTMiddleware: HS256 verify, blocklist check (Redis), fail-closed 503 |
| `app/middleware/signature.py` | SignatureMiddleware: ASGI-level HMAC-SHA256 webhook auth, body replay |
| `app/middleware/rate_limit.py` | Per-user rpm+burst (webhook), per-email auth rate limit; sync Redis in async context |
| `app/routers/auth.py` | POST /auth/token: bcrypt check, JWT HS256 issue, RLS tenant context for query |
| `app/tools/__init__.py` | TOOL_REGISTRY dispatch |
| `app/integrations/` | Linear, Telegram, Sheets API clients |
| `alembic/versions/` | 0001 (16 tables + RLS + roles), 0002 (gdev_admin BYPASSRLS), 0003 (password_hash) |
| `fakeredis/__init__.py` | Custom fake Redis for tests — in project root (should be under `tests/`) |
| `tests/` | 23 test files; no `test_isolation.py` yet |

---

## CP2 — High-Risk Modules

| Module | Risk |
|--------|------|
| `app/middleware/auth.py` | JWT validation; fail-closed 503 on Redis failure; all authenticated requests pass through |
| `app/middleware/signature.py` | HMAC webhook auth; raw body consumed and replayed at ASGI level; wrong body replay = auth bypass |
| `app/middleware/rate_limit.py` | Sync Redis in async `dispatch()` — blocks event loop; DoS defense bypassed on Redis failure |
| `app/routers/auth.py` | Issues JWTs; bcrypt timing attack protection; RLS tenant context setup is critical |
| `app/agent.py` | Core business logic; **approval cross-tenant check absent** — P0 security gap |
| `app/store.py` | Postgres writes without `SET LOCAL` — **RLS bypass** in production; thread-bridge pattern adds complexity |
| `app/dependencies.py` | `require_role()` is the RBAC enforcement point; any bug here affects all protected endpoints |
| `app/approval_store.py` | GETDEL atomicity is the sole race-condition guard on approvals |
| `app/tenant_registry.py` | Config cache; stale config could cause budget/category rule bypasses |
| `app/secrets_store.py` | Fernet key management; plaintext secret in memory during request |
| `app/config.py` | Two instantiation paths: `get_settings()` (validated) and `Settings()` (unvalidated) |
| `app/guardrails/output_guard.py` | Output secret scan; URL allowlist filtering; confidence floor enforcement |
| `app/main.py` | `_middleware_settings = Settings()` at module load — pre-lifespan Redis client |
| `app/db.py` | `SET LOCAL` is the RLS boundary; if omitted, tenant isolation fails silently |
| `alembic/versions/0001_initial_schema.py` | RLS policy definitions; `TENANT_SCOPED_TABLES` list determines what's protected |

---

## CP3 — Documentation Status

| Document | Status | Notes |
|----------|--------|-------|
| `docs/spec.md` | Partially outdated | §4 mandates `{tenant_id}:` Redis prefix — not implemented; §5.1 mandates RS256 — not implemented; §5.8 startup-fail on missing APPROVE_SECRET — not implemented |
| `docs/ARCHITECTURE.md` | Mostly accurate | REVIEW_NOTES.md §5.12 referenced — file does not exist |
| `docs/data-map.md` | Outdated | §3 Redis keys show tenant-prefixed patterns; code uses flat keys |
| `docs/tasks.md` | Accurate | T07 done, T08 pending — matches implementation |
| `docs/CODEX_PROMPT.md` | v2.5 — needs v2.6 | Phase 2 findings not yet documented |
| `docs/PHASE1_REVIEW.md` | Accurate | All Phase 1 issues resolved as documented |
| `docs/dev-standards.md` | Accurate | Violations exist in code (agent.py imports HTTPException) |
| `docs/N8N.md` | Accurate | References `REVIEW_NOTES.md §5.12` — file missing |
| `docs/adr/003-rbac-design.md` | **Outdated** | States RS256; implementation uses HS256; no JWKS endpoint |

---

## Critical Issues (P0)

---

### P0-1 · `/approve` endpoint has no cross-tenant tenant_id validation

**Symptom:**
A JWT-authenticated `support_agent` from Tenant A can approve a pending action belonging to Tenant B by supplying any valid `pending_id`.

**Evidence:**

```python
# app/main.py:202-214
@app.post("/approve", response_model=ApproveResponse)
def approve(
    payload: ApproveRequest,
    request: Request,
    _: None = require_role("support_agent", "tenant_admin"),
) -> ApproveResponse:
    provided = request.headers.get("X-Approve-Secret", "")
    if app.state.settings.approve_secret and not hmac.compare_digest(
        app.state.settings.approve_secret, provided
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return app.state.agent.approve(payload)  # ← request.state.tenant_id never passed
```

```python
# app/agent.py:233-257
def approve(self, request: ApproveRequest) -> ApproveResponse:
    pending = self.approval_store.pop_pending(request.pending_id)
    if not pending:
        raise HTTPException(status_code=404, detail="pending_id not found")
    tenant_id = pending.action.payload.get("tenant_id")  # ← never validated against JWT
    # ... executes action immediately
```

There is no check that `pending.action.payload["tenant_id"]` matches `request.state.tenant_id` (the JWT tenant). The `AgentService.approve()` receives no tenant context from the caller.

**Root Cause Hypothesis:**
Cross-tenant approval check was specified in CODEX_PROMPT security requirements but not implemented during T07. `PendingDecision` also lacks a top-level `tenant_id` field, making the check fragile (relies on `action.payload.get("tenant_id")`).

**Impact / Risk:**
Cross-tenant authorization bypass. In a multi-tenant deployment, any authenticated user who learns a `pending_id` (e.g., via log leakage, Telegram interception, timing) can approve or reject actions belonging to another tenant. Severity: Critical for multi-tenant use.

**Location:**
- `app/main.py:202-214`
- `app/agent.py:233-286`
- `app/schemas.py:61-70` (PendingDecision — missing top-level `tenant_id`)

**Proposed Fix (high level):**
1. Add `tenant_id: str` field to `PendingDecision` schema.
2. Populate `pending.tenant_id` in `agent.propose_action()`.
3. Pass `request.state.tenant_id` from the route handler to `agent.approve()`.
4. In `approve()`, verify `str(pending.tenant_id) == str(jwt_tenant_id)` before `pop_pending()`.
5. Return HTTP 403 (not 404) on mismatch to avoid leaking existence of pending_id.

**Verification Steps:**
- Create a pending action for Tenant A. Authenticate as Tenant B user with `support_agent` role. Attempt `POST /approve`. Should return 403.
- Create a pending action for Tenant A. Authenticate as Tenant A user with `support_agent` role. Should succeed.
- `tests/test_isolation.py` must include this cross-tenant approval test.

**Confidence:** High

---

### P0-2 · `EventStore._persist_pipeline_run_async()` opens DB session without `SET LOCAL`

**Symptom:**
In production with `gdev_app` DB user (no `BYPASSRLS`), all INSERTs to RLS-protected tables (`tickets`, `ticket_classifications`, `ticket_extracted_fields`, `proposed_actions`, `audit_log`) fail with "ERROR: new row violates row-level security policy for table".

**Evidence:**

```python
# app/store.py:127-131
async with self._db_session_factory() as session:
    async with session.begin():
        ticket_row = await session.execute(
            text("INSERT INTO tickets (...) VALUES (...) RETURNING ticket_id"),
            {...},
        )
```

No `SET LOCAL app.current_tenant_id = :tid` is called before the INSERTs.

The RLS policy:
```sql
-- alembic/versions/0001_initial_schema.py:362-364
CREATE POLICY tenant_isolation ON tickets
USING (tenant_id = current_setting('app.current_tenant_id', TRUE)::UUID)
```

With `missing_ok=TRUE`, `current_setting('app.current_tenant_id', TRUE)` returns NULL when the setting is absent. `tenant_id = NULL::UUID` evaluates to NULL, which is treated as FALSE by PostgreSQL RLS, blocking all rows. For INSERT, PostgreSQL uses the USING expression as the WITH CHECK expression when no explicit WITH CHECK is defined, so the INSERT is rejected.

**Root Cause Hypothesis:**
T08 task (EventStore Postgres integration) pre-existed the EventStore's RLS design awareness. The code was added before the `get_db_session()` pattern was established. The pattern is documented and works elsewhere (e.g., `auth.py`), but `store.py` uses a raw session from `db_session_factory()` without the SET LOCAL step.

**Impact / Risk:**
All `persist_pipeline_run()` calls silently fail in production. The webhook request succeeds from the caller's perspective (exception is swallowed in the `_run_blocking()` wrapper if not propagated), but no Postgres records are written. Audit logs, ticket records, and classification data are lost. This is an operational data loss issue on every webhook call.

**Why tests pass:** Tests use SQLite (no RLS) or testcontainers Postgres connected as superuser (BYPASSRLS implicit). Neither path exercises the RLS policy under `gdev_app`.

**Location:**
- `app/store.py:127-267` (`_persist_pipeline_run_async()`)

**Proposed Fix (high level):**
Before the first `session.begin()` block, execute `SET LOCAL app.current_tenant_id = :tid` with `payload_tenant_id`. The `tenant_id` is already validated at `store.py:117-123`, so it can be used directly. Alternatively, restructure `EventStore` to use the `get_db_session` dependency pattern.

**Verification Steps:**
- Integration test using testcontainers Postgres with RLS enabled and `gdev_app` role (no BYPASSRLS).
- Call `persist_pipeline_run()` with a valid tenant_id; assert ticket row created in DB.
- Call without SET LOCAL; assert RLS error is raised (existing prod-equivalent behavior).

**Confidence:** High

---

## Major Issues (P1)

---

### P1-1 · ADR-003 mandates RS256; implementation uses HS256 with no JWKS endpoint

**Symptom:**
JWT tokens are signed and verified with HS256 (symmetric HMAC). ADR-003 specifies RS256 (asymmetric). No `/auth/jwks.json` endpoint exists.

**Evidence:**
```python
# app/config.py:43
jwt_algorithm: str = "HS256"

# app/routers/auth.py:94
token = jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)

# docs/adr/003-rbac-design.md:53
# "JWT signed with RS256 (asymmetric). Public key published at /auth/jwks.json."
```

**Root Cause Hypothesis:**
HS256 was likely chosen for simplicity during T05/T06. The ADR decision has not been revisited.

**Impact / Risk:**
With HS256, any component holding `JWT_SECRET` can forge tokens for any tenant and any role. In a multi-component architecture (e.g., n8n, separate worker processes), this means the signing key must be shared and rotated across all components simultaneously. RS256 would allow public key distribution without exposing the signing secret. The current default `jwt_secret = "dev-jwt-secret-must-be-at-least-32b"` is 34 bytes — no startup warning fires, so this weak default can reach production unnoticed.

**Location:**
- `app/config.py:42-43`
- `app/routers/auth.py:94`
- `app/middleware/auth.py:43-47`
- `docs/adr/003-rbac-design.md`

**Proposed Fix (high level):**
Decide: either update ADR-003 to accept HS256 for v1 (with documented rationale and rotation plan), or implement RS256. If keeping HS256, remove the JWKS reference from ADR-003 and add `jwt_secret` validation: length ≥ 32 bytes enforced at startup (not just logged). If moving to RS256: use `python-jose` RSA key support, add `/auth/jwks.json` endpoint.

**Verification Steps:**
- If HS256 accepted: ADR-003 updated; startup fails on short jwt_secret; mypy clean.
- If RS256 implemented: `jwt.decode()` uses RS256; public key served at `/auth/jwks.json`.

**Confidence:** High

---

### P1-2 · `RateLimitMiddleware` calls synchronous Redis inside `async dispatch()` — blocks event loop

**Symptom:**
Every request to `/webhook` or `/auth/token` that hits a rate check blocks the uvicorn event loop for the duration of the Redis round-trip (typically 1–5 ms; worse under load).

**Evidence:**
```python
# app/main.py:153-157
app.add_middleware(
    RateLimitMiddleware,
    settings=_middleware_settings,
    redis_client=redis.from_url(_middleware_settings.redis_url),  # ← sync client
)

# app/middleware/rate_limit.py:18-53
class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        ...
        minute_count = int(self.redis.incr(minute_key))  # ← sync call inside async
        self.redis.expire(minute_key, 60)                # ← sync call inside async
        burst_count = int(self.redis.incr(burst_key))    # ← sync call inside async
        self.redis.expire(burst_key, 10)                 # ← sync call inside async
```

The synchronous Redis client's methods are blocking TCP socket calls. This is identical to the P1-01 issue fixed for `TenantRegistry` in T00A, but re-introduced in T06B for rate limiting.

**Root Cause Hypothesis:**
The middleware requires a Redis client and uses `BaseHTTPMiddleware`. The T00A fix was applied to `TenantRegistry` (an async service) but not to the rate limiter (added in T06B).

**Impact / Risk:**
All `/webhook` and `/auth/token` requests incur event loop blocking on every Redis incr/expire call. Under load (100 RPM per user), this is ~4 sync Redis calls per request, adding measurable latency spikes and reducing concurrency of the uvicorn worker.

**Location:**
- `app/middleware/rate_limit.py:53-76`
- `app/main.py:153-157`

**Proposed Fix (high level):**
Pass an `async` Redis client (from `redis.asyncio.from_url()`) to `RateLimitMiddleware`. Change all `self.redis.incr()` / `self.redis.expire()` calls to `await self.redis.incr()` / `await self.redis.expire()`. The async client should be shared with, or created alongside, the lifespan's async Redis client — not at module load time.

**Verification Steps:**
- `isinstance(self.redis, redis.asyncio.Redis)` assertion in test.
- Confirm `dispatch()` uses `await` on all Redis calls.
- Full test suite still passes.

**Confidence:** High

---

### P1-3 · Double `Settings()` and synchronous Redis instantiated at module load

**Symptom:**
`_middleware_settings = Settings()` and `redis.from_url(_middleware_settings.redis_url)` execute at `app/main.py:148` and `156` respectively — before the `lifespan` context manager runs. This creates a second, unvalidated Settings instance and a second Redis connection pool.

**Evidence:**
```python
# app/main.py:147-158
app = FastAPI(title="gdev-agent", lifespan=lifespan)
_middleware_settings = Settings()  # line 148 — second Settings; no ANTHROPIC_API_KEY validation

app.add_middleware(RequestIDMiddleware)
app.add_middleware(JWTMiddleware, settings=_middleware_settings)
app.add_middleware(
    RateLimitMiddleware,
    settings=_middleware_settings,
    redis_client=redis.from_url(_middleware_settings.redis_url),  # line 156 — second Redis pool
)
app.add_middleware(SignatureMiddleware, settings=_middleware_settings)
```

`get_settings()` (lru_cache, validated) and `Settings()` (unvalidated, can succeed without ANTHROPIC_API_KEY) are two separate code paths. The lifespan's `settings = get_settings()` validates API key; `_middleware_settings = Settings()` does not. A misconfigured environment could start with ANTHROPIC_API_KEY missing, with lifespan failing on first request rather than at startup.

**Root Cause Hypothesis:**
Middleware registration must happen at module load time (before lifespan), but the middleware needs Settings. The solution is to use lazy `app.state` access or a shared settings singleton, but instead a second `Settings()` was created.

**Impact / Risk:**
- Two Redis connection pools consuming sockets and memory unnecessarily.
- Unvalidated Settings in middleware could use a different `redis_url` if `.env` is mutated between startup phases (rare, but possible in tests).
- `_middleware_settings.jwt_secret` default value is 34 bytes — startup warning in lifespan (len < 32) never fires for `_middleware_settings`, only for `get_settings()`.

**Location:**
- `app/main.py:148,156`

**Proposed Fix (high level):**
Use `get_settings()` (the validated, cached singleton) instead of `Settings()` for `_middleware_settings`. The lru_cache ensures it's the same object. Delay Redis client creation to lifespan (e.g., pass via app.state). For the rate-limit Redis client, once P1-2 is fixed to use async, it can be shared with the lifespan's `tenant_registry_redis` client.

**Verification Steps:**
- Only one `Settings()` instantiation in codebase (from lru_cache).
- Only one Redis connection pool per logical Redis URL at runtime.
- Test: `app.state.settings is _middleware_settings` (same object).

**Confidence:** High

---

## Major Issues (P2)

---

### P2-1 · Redis keys lack tenant namespace — cross-tenant collision risk

**Symptom:**
`spec.md §4` and `data-map.md §3` mandate `{tenant_id}:` prefix on all Redis keys. Implemented keys use flat namespace.

**Evidence:**
```python
# app/dedup.py:17 — "dedup:{message_id}"
# app/approval_store.py:23 — "pending:{pending_id}"
# app/middleware/rate_limit.py:51 — "ratelimit:{user_id}"

# data-map.md §3 (spec):
# {tenant_id}:dedup:{message_id}
# {tenant_id}:pending:{pending_id}
# {tenant_id}:ratelimit:{user_id}
```

**Impact / Risk:**
In a multi-tenant deployment where two tenants submit the same `message_id` (e.g., both use sequential integer message IDs from their own Telegram bots), the dedup cache from Tenant A will return Tenant B's cached response. For `pending:{id}`, a pending_id collision between tenants is unlikely (32-char hex uuid) but architecturally not enforced. Rate limits are shared across tenants for the same user_id string.

**Proposed Fix (high level):**
Add tenant prefix to dedup and rate-limit keys. The `pending_id` is a uuid4 hex, so collision is negligible, but the prefix should be added for consistency. Note: changing Redis key patterns is breaking for in-flight requests.

**Confidence:** High (spec violation confirmed)

---

### P2-2 · `store.py` event-loop bridging pattern adds latency on every webhook call

**Symptom:**
`EventStore._run_blocking()` spawns a new OS thread per webhook call to run an async coroutine in a new event loop. This adds thread-spawn and synchronization overhead.

**Evidence:**
```python
# app/store.py:83-104
def _run_blocking(self, coroutine):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    queue: Queue = Queue(maxsize=1)
    def _target() -> None:
        result = asyncio.run(coroutine)
        queue.put((True, result))
    thread = Thread(target=_target, daemon=True)
    thread.start()
    ok, data = queue.get()
    thread.join()
```

The webhook route handler (`def webhook()`) is synchronous and runs in FastAPI's thread pool executor. `_run_blocking()` spawns an additional thread per request. Under load, this creates thread churn and queue synchronization overhead.

**Proposed Fix (high level):**
Convert `/webhook` to `async def`; use `asyncio.create_task()` for the DB write as a background task. Alternatively, use FastAPI `BackgroundTasks`. This eliminates thread spawning entirely. Address as part of T08 rewrite.

**Confidence:** High

---

### P2-3 · `kb_base_url` defaults to `https://kb.example.com` which is not in `URL_ALLOWLIST`

**Symptom:**
When the LLM calls `lookup_faq` and includes KB article URLs in the draft reply, those URLs are stripped by `output_guard.py` because `kb.example.com` is not in `url_allowlist` (default is `[]`).

**Evidence:**
```python
# app/config.py:11-12,24
DEFAULT_KB_BASE_URL = "https://kb." + "example.com"
kb_base_url: str = DEFAULT_KB_BASE_URL

# app/llm_client.py:271-274
return {
    "articles": [
        {"title": f"FAQ: {keyword}", "url": f"{self.settings.kb_base_url}/{keyword}"}
    ]
}
# → URL like "https://kb.example.com/billing" included in draft text

# app/guardrails/output_guard.py:46-52
for url in _URL_PATTERN.findall(draft):
    host = (urlparse(url).hostname or "").lower()
    if host in self.settings.url_allowlist:  # ← kb.example.com not in []
        continue
    redacted = redacted.replace(url, "").strip()  # ← URL stripped silently
```

**Impact / Risk:**
FAQ lookup silently produces useless results for any deployment using the default `KB_BASE_URL`. Operators may not notice because the draft is returned without error — just without the FAQ links.

**Proposed Fix (high level):**
Add `KB_BASE_URL` to `.env.example` as a required variable (no default). OR: validate at startup that `kb_base_url` is in `url_allowlist` if `kb_base_url` is non-empty; warn if not. Include in T08 pre-flight.

**Confidence:** High

---

### P2-4 · Observability layer entirely absent

**Symptom:**
dev-standards §7 mandates OTel child spans, Prometheus counters, and Prometheus histograms on every service method. No `app/metrics.py` exists. No tracer is configured. No Prometheus metrics are emitted anywhere in the codebase.

**Evidence:**
```bash
# find app/ -name "metrics.py" → empty
# grep -r "from opentelemetry" app/ → zero results
# grep -r "prometheus_client" app/ → zero results
```

**Impact / Risk:**
No latency histograms, no tenant-level request counters, no LLM cost metrics. The load-profile SLAs (p99 < 3s, cost ≤ $0.015/req) cannot be monitored in production.

**Proposed Fix (high level):**
Create `app/metrics.py` with Prometheus metric definitions (as a deferred task, not T08). Add `prometheus-client` to `requirements.txt`. Wire metrics to `AgentService.process_webhook()` and route handlers. OTel traces can follow in a dedicated task.

**Confidence:** High

---

### P2-5 · `REVIEW_NOTES.md` referenced in N8N.md but does not exist

**Symptom:**
`docs/N8N.md §8.8` references `REVIEW_NOTES.md §5.12` for approval notification failure mitigation. The file does not exist in the `docs/` directory.

**Evidence:**
```
# docs/N8N.md:477
See `REVIEW_NOTES.md §5.12` for mitigation guidance.

# ls docs/ → no REVIEW_NOTES.md
```

**Proposed Fix:** Remove or replace the reference in N8N.md with a concrete note.

**Confidence:** High

---

### P2-6 · `AgentService` imports `HTTPException` from `fastapi` — violates service layer boundary

**Symptom:**
`app/agent.py:13` imports `HTTPException` from FastAPI. Services should not depend on the HTTP framework.

**Evidence:**
```python
# app/agent.py:13
from fastapi import HTTPException
```

This couples the service to FastAPI, making unit testing require FastAPI's test scaffolding and violating dev-standards §3.2.

**Proposed Fix (high level):**
Define domain exceptions (`PendingNotFoundError`, `AgentGuardError`) in `app/agent.py` or `app/exceptions.py`. Route handlers catch domain exceptions and translate to HTTPException. Defer to Phase 2 cleanup task.

**Confidence:** High

---

### P2-7 · `ApproveRequest.reviewer` accepts raw PII; stored unhashed in audit log

**Symptom:**
`data-map.md` specifies `approved_by: TEXT -- 'auto' or reviewer email_hash`. But `reviewer` is passed directly from the API caller (Telegram user ID string) and written to audit log as-is.

**Evidence:**
```python
# app/schemas.py:88-90
class ApproveRequest(BaseModel):
    pending_id: str
    approved: bool = True
    reviewer: str | None = None  # ← raw PII potential

# app/agent.py:267
"reviewer": request.reviewer,  # ← stored directly in event log
```

N8N sends `reviewer = str(from.id)` (Telegram numeric user ID). This is Medium-PII per data-map §5. It should be hashed before storage.

**Proposed Fix:** Hash `reviewer` with SHA-256 before storing in any log or audit record.

**Confidence:** Medium (depends on whether Telegram user ID counts as PII)

---

## Improvements (P3)

---

### P3-1 · Startup does not fail on missing `APPROVE_SECRET` (spec §5.8 violation)

`spec.md §5.8` says "`APPROVE_SECRET` and `WEBHOOK_SECRET` are required in production; startup fails if absent." Current code emits a `LOGGER.warning()` but continues. `approve_secret` defaults to `None`, allowing unauthenticated approval calls in production.

**Location:** `app/main.py:71-80`

---

### P3-2 · `fakeredis/__init__.py` is in project root — should be under `tests/`

The custom fake Redis module at `fakeredis/__init__.py` is in the project root directory. Per dev-standards §1.1, test helpers belong in `tests/`. The current location pollutes the module namespace and could be accidentally imported in production code.

**Location:** `fakeredis/`

---

### P3-3 · `_append_audit_async` uses fire-and-forget `run_in_executor` without error capture

```python
# app/agent.py:406-407
loop.run_in_executor(None, self.sheets_client.append_log, entry)
return
```
The future returned by `run_in_executor()` is not awaited or logged. If Sheets fails, the error is silently lost.

---

### P3-4 · Default `jwt_secret` (34 bytes) does not trigger startup warning

`config.py:42`: `jwt_secret: str = "dev-jwt-secret-must-be-at-least-32b"` is 34 bytes. The startup check in `main.py:81` is `if len(settings.jwt_secret) < 32`, so the default passes silently. A distinct sentinel value (e.g., `""` with a check for non-empty) would be safer.

---

## Architecture Consistency Check

| Spec/ADR | Doc Says | Implementation | Gap |
|---|---|---|---|
| ADR-003 | RS256 + JWKS endpoint | HS256, no JWKS | **Architectural deviation** |
| spec.md §4 | `{tenant_id}:` Redis prefix | Flat namespace | **Not implemented** |
| CODEX_PROMPT §SECURITY | Cross-tenant approval check | Absent | **Not implemented** |
| CODEX_PROMPT §SECURITY | Budget check before LLM call | No CostLedger exists | **Not implemented** |
| dev-standards §7 | OTel + Prometheus on all service methods | No observability at all | **Not implemented** |
| dev-standards §3.2 | Services not importing FastAPI | `agent.py` imports `HTTPException` | Violates standard |
| spec.md §5.8 | Startup fail on missing APPROVE_SECRET | Only warning | Not enforced |

---

## Security Review

| Area | Finding | Severity |
|------|---------|----------|
| Approval cross-tenant isolation | Absent — P0-1 | P0 |
| EventStore RLS bypass | Silent data loss — P0-2 | P0 |
| JWT algorithm | HS256 vs ADR RS256 | P1 |
| Default jwt_secret | 34 bytes, no warning | P3 |
| Rate limiter sync Redis | Event loop blocking | P1 |
| APPROVE_SECRET optional | No startup enforcement | P3 |
| Reviewer PII in audit log | Unhashed Telegram ID | P2 |
| Injection guard | `INJECTION_PATTERNS` tuple is effective | ✓ |
| HMAC webhook auth | Per-tenant, Fernet-encrypted, replay protection | ✓ |
| JWT blocklist | Fail-closed 503 on Redis failure | ✓ |
| bcrypt timing | Dummy hash prevents user enumeration | ✓ |
| Email in logs | SHA-256 hashed; not raw | ✓ |
| SQL parameterization | All queries use named params | ✓ |
| Output guard | Secret patterns + URL allowlist + confidence floor | ✓ |

---

## Testing Review

| Gap | Risk | Action |
|-----|------|--------|
| `tests/test_isolation.py` absent | Cross-tenant RLS and approval bypass untested | T09 |
| EventStore RLS integration test absent | P0-2 invisible in unit tests | Add integration test with gdev_app role |
| RateLimitMiddleware async client not tested | P1-2 invisible | Add test asserting async Redis calls |
| RS256/JWKS absent | P1-1 untested | Add after ADR resolution |
| `approve` cross-tenant test absent | P0-1 untested | Add to T09 scope |
| Budget exhaustion test absent | CostLedger not implemented | T10 |

Existing baseline: **85 pass, 1 skipped** (`test_isolation.py` absent — T09).

---

## Documentation Accuracy Review

| Document | Action Required |
|----------|----------------|
| `docs/adr/003-rbac-design.md` | Update to reflect HS256 decision (or change to RS256); remove JWKS endpoint reference |
| `docs/data-map.md §3` | Clarify Redis key pattern drift: document current flat-key implementation; note tenant-prefix as Phase 5 hardening |
| `docs/N8N.md §8.8` | Remove dangling `REVIEW_NOTES.md §5.12` reference; add inline note |
| `docs/CODEX_PROMPT.md` | Bump to v2.6; add Phase 2 Review Findings section |

---

## Known Issues — Status Update

| Issue (MEMORY) | Status | Evidence |
|---|---|---|
| JsonFormatter drops `exc_info` | ✅ **RESOLVED** | `logging.py:40-41` correctly calls `self.formatException(record.exc_info)` |
| `rate_limit_burst` not enforced | ✅ **RESOLVED** | `rate_limit.py:61` checks both `rate_limit_rpm` and `rate_limit_burst` |
| Double Settings/Redis at module load | 🔴 **OPEN** | `main.py:148,156` — confirmed; added to P1-3 |
| Dead `redis.delete()` after GETDEL | ✅ **RESOLVED** | `approval_store.py:30-41` — no dead delete present |
| Deprecated `asyncio.get_event_loop()` | ✅ **RESOLVED** | `agent.py:405` uses `asyncio.get_running_loop()` |
| Missing `Retry-After` header on 429 | ✅ **RESOLVED** | `rate_limit.py:65` includes `"Retry-After": "60"` header |
| Hardcoded `kb.example.com` not in allowlist | 🔴 **OPEN** | Confirmed — added to P2-3 |

---

## Stop-Ship Decision

**STOP-SHIP: YES**

P0-1 (cross-tenant approval bypass) is a critical security defect that allows an authenticated user from one tenant to approve or reject actions belonging to another tenant. This is an authorization breach in any multi-tenant deployment.

P0-2 (EventStore RLS bypass) causes silent data loss on every webhook call in production. The system appears functional (HTTP 200 returned) but no audit or ticket records are persisted.

Both P0 issues must be resolved before any multi-tenant deployment. Single-tenant internal environments can proceed with awareness of the risk.

P1-2 (sync Redis in async middleware) degrades performance under load and should be fixed before any load testing or production traffic.
