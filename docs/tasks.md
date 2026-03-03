# gdev-agent — Implementation TaskGraph v1.0

_Owner: Architecture · Date: 2026-03-03_
_This document is the authoritative task contract for Codex and human reviewers._
_All tasks reference `docs/spec.md`, `docs/architecture.md`, and `docs/data-map.md` as the governing contract._
_No task is started without reading its "Depends-On" chain first._

---

## Legend

| Field | Meaning |
|---|---|
| Owner | `Codex` = AI-generated diff; `Human` = requires judgement/auth; `Both` = Codex drafts, Human reviews |
| Status | `pending` / `in_progress` / `done` |
| Priority | `P0` = blocks everything; `P1` = blocks scale; `P2` = quality/ops |

---

## Phase 1 — Storage Foundation (Target: Week 1)

---

### T01 · Alembic Setup + Initial Schema Migration

**Owner:** Codex
**Priority:** P0
**Depends-on:** —
**Status:** done

**Scope:**
Install Alembic, configure it for async SQLAlchemy, and produce the first migration file that
creates all tables from `docs/data-map.md §2`.

**Files to CREATE (do not exist yet — create from scratch):**
- `alembic.ini` (root)
- `alembic/env.py` — async engine; reads `DATABASE_URL` from settings
- `alembic/versions/0001_initial_schema.py`
- `tests/test_migrations.py`

**Files to MODIFY (must exist — read before editing):**
- `app/config.py` — add `database_url: PostgresDsn` field
- `requirements.txt` or `pyproject.toml` — add `alembic`, `asyncpg`, `sqlalchemy[asyncio]`

**Tables to create (migration must include all):**
`tenants`, `tenant_users`, `api_keys`, `webhook_secrets`, `tickets`,
`ticket_classifications`, `ticket_extracted_fields`, `proposed_actions`,
`pending_decisions`, `approval_events`, `audit_log`, `ticket_embeddings`,
`cluster_summaries`, `agent_configs`, `cost_ledger`, `eval_runs`

**Schema rules:**
- Every table has `tenant_id UUID REFERENCES tenants(tenant_id)` except `tenants` itself.
- Every table has `created_at TIMESTAMPTZ DEFAULT NOW()`.
- All UUID columns default to `gen_random_uuid()`.
- `ticket_embeddings.embedding VECTOR(1536)` requires `CREATE EXTENSION IF NOT EXISTS vector`.

**RLS policies (in same migration file):**
```sql
ALTER TABLE tickets ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON tickets
  USING (tenant_id = current_setting('app.current_tenant_id', TRUE)::UUID);
-- Repeat pattern for all tenant-scoped tables.
-- Use current_setting with missing_ok=TRUE to avoid errors during admin operations.
```

**Two DB roles:**
```sql
CREATE ROLE gdev_app NOINHERIT LOGIN;       -- application; no BYPASSRLS
CREATE ROLE gdev_admin NOINHERIT LOGIN;     -- migrations; BYPASSRLS
GRANT ALL ON ALL TABLES IN SCHEMA public TO gdev_admin;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO gdev_app;
```

**Acceptance Criteria:**
1. `alembic upgrade head` runs without error against a fresh Postgres instance.
2. `alembic downgrade -1` rolls back cleanly.
3. `psql -c "\dt"` shows all 16 tables.
4. RLS policy on `tickets` blocks cross-tenant reads (verified in T09 test).
5. `python -c "import app.config; app.config.get_settings()"` does not fail when `DATABASE_URL` is set.

**Tests required:**
- `tests/test_migrations.py` — spin up a test Postgres (testcontainers), run `upgrade head`, assert all tables exist, run `downgrade base`, assert all tables gone.

**Notes / Gotchas:**
- `current_setting('app.current_tenant_id', TRUE)` — the `TRUE` (missing_ok) flag is required, otherwise Alembic migrations using `gdev_admin` role fail because the setting is not set during migration runs.
- `pgvector` extension must be installed on the Postgres instance before the migration runs. Add `CREATE EXTENSION IF NOT EXISTS vector;` at the top of the migration.
- Do NOT use `alembic --autogenerate` for RLS policies; they are not introspected. Write them manually.

---

### T02 · SQLAlchemy Async Engine + Session Management

**Owner:** Codex
**Priority:** P0
**Depends-on:** T01
**Status:** done

**Scope:**
Create an async SQLAlchemy engine and session factory. Replace the existing SQLite `EventStore`
with a Postgres-backed async session. Inject sessions via FastAPI dependency injection.

**Files to CREATE (do not exist yet — create from scratch):**
- `app/db.py` — `create_async_engine`, `async_sessionmaker`, `get_db_session` dependency
- `tests/test_db.py`

**Files to MODIFY (must exist — read before editing):**
- `app/main.py` — create engine in lifespan; store on `app.state.db_engine`
- `app/store.py` — refactor `EventStore` to use async SQLAlchemy session
- `app/config.py` — add `db_pool_size: int = 5`, `db_max_overflow: int = 10`

**Design:**
```python
# app/db.py
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

def make_engine(settings: Settings):
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
    )

async def get_db_session(request: Request) -> AsyncSession:
    async with request.app.state.db_session_factory() as session:
        # Set RLS tenant context on every session before yielding
        tenant_id = request.state.tenant_id  # injected by TenantMiddleware (T05)
        if tenant_id:
            await session.execute(
                text("SET LOCAL app.current_tenant_id = :tid"),
                {"tid": str(tenant_id)}
            )
        yield session
```

**Key constraint:**
`SET LOCAL app.current_tenant_id` scopes to the current transaction, not the connection.
This is safe with connection pooling — no risk of one tenant's context leaking to another request.
Never use `SET` (session-level) for this.

**Acceptance Criteria:**
1. `app.state.db_engine` is created in lifespan and closed on shutdown.
2. `get_db_session` yields a session with `SET LOCAL app.current_tenant_id` already executed.
3. No module-level engine creation (no `create_engine()` at import time).
4. Existing tests pass with an in-memory SQLite fallback for unit tests (use `TEST_DATABASE_URL=sqlite+aiosqlite:///:memory:`).

**Tests required:**
- `tests/test_db.py` — mock engine; assert `SET LOCAL` is called with correct tenant_id.

**Notes:**
- Do not use `Session.execute(text("SET app.current_tenant_id = ..."))` — that is session-level and leaks across pool reuse.
- If `tenant_id` is None (e.g., health check route), skip the SET. RLS will block all tenant-scoped reads with a Postgres error, which is correct.

---

### T03 · TenantRegistry Service

**Owner:** Codex
**Priority:** P0
**Depends-on:** T01, T02
**Status:** pending

**Scope:**
Implement `TenantRegistry` that loads tenant config from Postgres and caches it in Redis with a
5-minute TTL. Used by all middleware and services to resolve tenant settings.

**Files to CREATE (do not exist yet — create from scratch):**
- `app/tenant_registry.py`
- `tests/test_tenant_registry.py`

**Files to MODIFY (must exist — read before editing):**
- `app/main.py` — instantiate `TenantRegistry` in lifespan; store on `app.state`

**Schema backing this service:**
```python
# app/tenant_registry.py
@dataclass
class TenantConfig:
    tenant_id: UUID
    slug: str
    daily_budget_usd: Decimal
    approval_ttl_s: int
    auto_approve_threshold: float
    approval_categories: list[str]
    url_allowlist: list[str]
    is_active: bool
```

**Cache strategy:**
- Redis key: `tenant:{tenant_id}:config` (JSON, TTL 300 s)
- On miss: SELECT from `tenants` WHERE `tenant_id = $1` AND `is_active = TRUE`
- On tenant not found or `is_active=FALSE`: raise `TenantNotFoundError` → caller returns HTTP 401
- Cache invalidation: explicit `TenantRegistry.invalidate(tenant_id)` method (called on `PUT /agents` or config update)

**Acceptance Criteria:**
1. Cache hit returns in < 1 ms (Redis round-trip).
2. Cache miss hits Postgres, populates Redis, returns config.
3. Inactive tenant raises `TenantNotFoundError`.
4. Missing tenant raises `TenantNotFoundError`.
5. `invalidate(tenant_id)` deletes the Redis key.

**Tests required:**
- `tests/test_tenant_registry.py` — mock Redis + Postgres; test hit, miss, inactive, missing, invalidate.

**Notes:**
- Do NOT expose `webhook_secret` via this service. Webhook secrets are fetched separately in T04 via a dedicated query with no caching (secrets must not appear in Redis).

---

### T04 · Per-Tenant HMAC Secret Lookup in SignatureMiddleware

**Owner:** Codex
**Priority:** P0
**Depends-on:** T01, T02, T03
**Status:** pending

**Scope:**
The current `SignatureMiddleware` uses a single global `WEBHOOK_SECRET`. Multi-tenant requires
per-tenant secrets stored encrypted in Postgres (`webhook_secrets` table).

**Files to modify:**
- `app/middleware/signature.py`
- `app/config.py` — add `webhook_secret_encryption_key: str` (Fernet key)
- `app/db.py` or new `app/secrets_store.py`

**Design:**
- `webhook_secrets` table stores `secret_ciphertext TEXT` (Fernet-encrypted).
- On each webhook request: extract `tenant_id` from the JWT or a `X-Tenant-Id` header (pre-auth).
- Look up and decrypt the secret. No caching — secrets are not stored in Redis.
- Validate HMAC as before. Secret mismatch → HTTP 401.

**Tenant identification before JWT validation:**
The webhook endpoint must identify the tenant before JWT validation so that the correct HMAC
secret is used. Use `X-Tenant-Slug` header (unauth'd, informational) to resolve tenant_id for
HMAC check. The JWT is then validated second.

**Acceptance Criteria:**
1. Two tenants with different secrets: request signed with Tenant A's secret rejected on Tenant B's endpoint.
2. Missing `X-Tenant-Slug` → HTTP 400 (before HMAC check).
3. Unknown tenant slug → HTTP 401.
4. Correct secret → request proceeds.
5. No secret value appears in logs or spans.

**Tests required:**
- `tests/test_middleware.py` — extend existing tests; add multi-tenant HMAC cases.

**Notes:**
- Fernet is symmetric encryption; the `WEBHOOK_SECRET_ENCRYPTION_KEY` env var must be a URL-safe base64 Fernet key (32 bytes). Generate with `Fernet.generate_key()`.
- The old single `WEBHOOK_SECRET` env var is deprecated. Emit a startup warning if it's still set.
- For dev/test: provide a migration seed that inserts a test tenant with a known secret.

---

## Phase 2 — Auth & RBAC (Target: Week 2)

---

### T05 · JWT Middleware + Tenant Context Injection

**Owner:** Codex
**Priority:** P0
**Depends-on:** T03
**Status:** pending

**Scope:**
Implement JWT validation middleware using HS256 (v1 simplification; RS256 deferred to v2).
Extract `tenant_id` and `role` from validated JWT claims. Inject into `request.state`.

**Files to CREATE (do not exist yet — create from scratch):**
- `app/middleware/auth.py` — `JWTMiddleware`
- `app/dependencies.py` — `require_role()` dependency factory
- `tests/test_auth.py`

**Files to MODIFY (must exist — read before editing):**
- `app/config.py` — add `jwt_secret: str`, `jwt_algorithm: str = "HS256"`, `jwt_token_expiry_hours: int = 8`
- `app/main.py` — add `JWTMiddleware` to middleware stack (position: before rate limit, after RequestID)

**JWT claims structure:**
```json
{
  "sub": "<user_id UUID>",
  "tenant_id": "<UUID>",
  "role": "tenant_admin | support_agent | viewer",
  "jti": "<UUID>",
  "iat": 0,
  "exp": 0
}
```

**Middleware behavior:**
- Exempt routes: `GET /health`, `POST /webhook` (webhook uses HMAC auth, not JWT).
- All other routes: require `Authorization: Bearer <token>`.
- Missing/invalid token → HTTP 401.
- Expired token → HTTP 401 with `{"error": {"code": "token_expired", "message": "..."}}`
- Revoked token (JTI in Redis blocklist) → HTTP 401.
- Valid token: set `request.state.tenant_id`, `request.state.user_id`, `request.state.role`.

**Redis blocklist:**
- Key: `jwt:blocklist:{jti}` (STRING "1", TTL = remaining token lifetime in seconds)
- Check on every request (fast Redis GET).
- If Redis is unavailable: **log a CRITICAL alert and REJECT the request** (fail closed, not open).
  This is a deliberate security choice: a revoked JWT must not be accepted when blocklist is unreachable.

**Role enforcement dependency:**
```python
# app/dependencies.py
def require_role(*roles: str):
    def dependency(request: Request) -> None:
        if request.state.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient role")
    return Depends(dependency)
```

**Acceptance Criteria:**
1. Valid JWT → `request.state.tenant_id` and `request.state.role` set.
2. Expired JWT → HTTP 401 with `code: "token_expired"`.
3. Revoked JTI → HTTP 401 (checked against Redis blocklist).
4. Redis unavailable during blocklist check → HTTP 503 (fail closed).
5. `GET /health` does not require JWT.
6. `POST /webhook` does not require JWT (uses HMAC).

**Tests required:**
- `tests/test_auth.py` — happy path, expired, revoked, Redis-down (mock Redis to raise), exempt routes.

**Notes:**
- HS256 means the `JWT_SECRET` env var must be at least 32 bytes. Log a startup error if it's shorter.
- Do NOT store `role` in Postgres and re-read it on every request. The JWT is the authority. DB user
  role lookups are only for user management endpoints.
- `POST /webhook` gets `tenant_id` from the HMAC secret lookup (T04), not from JWT. The two paths
  must not be conflated.

---

### T06 · Auth Token Endpoint (`POST /auth/token`)

**Owner:** Codex
**Priority:** P1
**Depends-on:** T05
**Status:** pending

**Scope:**
Minimal token issuance endpoint. Users authenticate with email + password (bcrypt-hashed in
`tenant_users`). Returns a short-lived JWT.

**Files to CREATE (do not exist yet — create from scratch):**
- `app/routers/auth.py`

**Files to MODIFY (must exist — read before editing):**
- `app/main.py` — include `auth_router`
- `app/config.py` — confirm `jwt_secret`, `jwt_token_expiry_hours` are present
- `tests/test_auth.py` — extend with token endpoint tests (file created in T05)

**Endpoint:**
```
POST /auth/token
Body: {"email": "...", "password": "..."}
Response 200: {"access_token": "...", "token_type": "bearer", "expires_in": 28800}
Response 401: {"error": {"code": "invalid_credentials", "message": "..."}}
```

**Rate limiting:** Apply existing `RateLimitMiddleware` to `/auth/token` (prevents brute force).
Add a separate, stricter limit: 5 attempts per user per 60 seconds.

**Acceptance Criteria:**
1. Correct credentials → valid JWT with correct claims.
2. Wrong password → HTTP 401; login attempt is logged (hashed email, no password).
3. Unknown email → HTTP 401 (same response as wrong password; no user enumeration).
4. More than 5 attempts per user in 60 s → HTTP 429.
5. Password comparison uses `bcrypt.checkpw()` (constant-time).

**Tests required:**
- `tests/test_auth.py` — all 5 criteria above.

**Notes:**
- Never log the password field, even hashed.
- The response must not reveal whether the email exists ("invalid_credentials" for both cases).
- `tenant_users.password_hash` column must be added to the schema (not in current data-map; add in T01 or a separate migration).

---

### T07 · Role Enforcement on All Existing Endpoints

**Owner:** Codex
**Priority:** P0
**Depends-on:** T05
**Status:** pending

**Scope:**
Apply `require_role()` dependency to all route handlers. Apply `tenant_id` scoping to all
service calls. No endpoint may return data for a different tenant than the JWT's `tenant_id`.

**Enforcement matrix (from spec.md §8):**

| Endpoint | Minimum Role |
|---|---|
| `POST /webhook` | HMAC only (no JWT role check) |
| `POST /approve` | `support_agent` |
| `GET /tickets` | `viewer` |
| `GET /tickets/{id}` | `viewer` |
| `GET /clusters` | `viewer` |
| `GET /clusters/{id}` | `viewer` |
| `GET /audit` | `tenant_admin` |
| `GET /metrics/cost` | `tenant_admin` |
| `GET /agents` | `tenant_admin` |
| `PUT /agents/{id}` | `tenant_admin` |
| `POST /eval/run` | `tenant_admin` |
| `GET /eval/runs` | `viewer` |

**Acceptance Criteria:**
1. Viewer role calling `GET /audit` → HTTP 403.
2. support_agent calling `PUT /agents/{id}` → HTTP 403.
3. tenant_admin calling any endpoint → succeeds (assuming valid data).
4. No endpoint returns data with a `tenant_id` different from the JWT's `tenant_id`.
5. Postgres RLS provides the second layer: cross-tenant DB query returns zero rows, not an error.

**Tests required:**
- `tests/test_rbac.py` — test each role against each endpoint; confirm 403 on unauthorized combos.
- One integration test: make a valid query with Tenant A's JWT but inject Tenant B's data; assert zero rows returned (RLS verification).

**Notes:**
- The RLS test is the most important. Application-level role checks can be bypassed by bugs. RLS cannot.
- Add a CI step: `grep -rn "get_db_session" app/routers/` to verify every route that touches the DB goes through the dependency (which sets `SET LOCAL`).

---

## Phase 3 — Core Services + New Endpoints (Target: Week 2–3)

---

### T08 · Postgres-Backed EventStore (Tickets + Audit Log)

**Owner:** Codex
**Priority:** P0
**Depends-on:** T02, T07
**Status:** pending

**Scope:**
Replace the current SQLite/Sheets `EventStore` with a Postgres-backed async implementation.
Write tickets, classifications, extracted fields, proposed actions, and audit log entries on
every pipeline run.

**Files to modify:**
- `app/store.py` — rewrite `EventStore` class; keep the same public interface
- `app/agent.py` — pass `tenant_id` to all `store.*` calls
- `app/schemas.py` — add `tenant_id` to `AuditLogEntry`, `WebhookRequest`

**Write sequence (must be in a single transaction):**
```
1. INSERT tickets → get ticket_id
2. INSERT ticket_classifications (linked to ticket_id)
3. INSERT ticket_extracted_fields
4. INSERT proposed_actions
5. INSERT audit_log
```

If any step fails: rollback; return HTTP 500 to caller. Dedup cache prevents retry from
re-processing the same message.

**Acceptance Criteria:**
1. After `POST /webhook` (happy path), all 5 rows exist in Postgres.
2. Postgres write failure → HTTP 500; no partial rows committed.
3. `tenant_id` on all rows matches JWT/webhook tenant.
4. `user_id_hash` in `tickets` is `SHA-256(user_id)`, not the raw value.
5. Existing eval tests pass (EventStore mocked in eval mode).

**Tests required:**
- `tests/test_store.py` — async tests with testcontainers Postgres; verify all rows; verify rollback on failure; verify user_id hashing.

---

### T09 · Cross-Tenant Isolation Integration Test

**Owner:** Codex
**Priority:** P0
**Depends-on:** T07, T08
**Status:** pending

**Scope:**
Dedicated integration test suite that proves Tenant A cannot read Tenant B's data.
This test is a hard gate — no multi-tenant feature ships without it passing.

**Test cases:**
1. Create Tenant A + Tenant B with separate tickets.
2. Query `GET /tickets` with Tenant A's JWT → returns only Tenant A's tickets.
3. Query `GET /tickets/{ticket_id}` with Tenant A's JWT using Tenant B's `ticket_id` → HTTP 404.
4. Directly query Postgres with `SET LOCAL app.current_tenant_id = <tenant_a_id>` and query `SELECT * FROM tickets WHERE tenant_id = <tenant_b_id>` → zero rows.
5. Approval path: Tenant A attempts `POST /approve` with Tenant B's `pending_id` → HTTP 404 (pending not found for that tenant).

**Acceptance Criteria:**
All 5 test cases pass. Any cross-tenant data return is a P0 regression.

**Tests required:**
- `tests/test_isolation.py` — uses testcontainers Postgres with both tenants seeded.

---

### T10 · CostLedger Service + Budget Guard

**Owner:** Codex
**Priority:** P0
**Depends-on:** T02, T03
**Status:** pending

**Scope:**
Implement `CostLedger` service for real-time token accounting and pre-call budget enforcement.

**Files to CREATE (do not exist yet — create from scratch):**
- `app/cost_ledger.py`
- `tests/test_cost_ledger.py`

**Files to MODIFY (must exist — read before editing):**
- `app/agent.py` — add `CostLedger.check_budget()` call before each LLM call; `CostLedger.record()` after
- `app/config.py` — add `llm_input_rate_per_1k` and `llm_output_rate_per_1k` Decimal fields

**Key methods:**
```python
class CostLedger:
    async def check_budget(self, tenant_id: UUID, db: AsyncSession) -> None:
        """Raise BudgetExhaustedError if tenant has reached daily budget."""

    async def record(
        self, tenant_id: UUID, date: date,
        input_tokens: int, output_tokens: int, cost_usd: Decimal,
        db: AsyncSession
    ) -> None:
        """Atomic UPSERT to cost_ledger. Idempotent on conflict."""
```

**Budget check logic:**
- Query `cost_ledger WHERE tenant_id=$1 AND date=TODAY`.
- If `cost_usd >= tenant.daily_budget_usd` → raise `BudgetExhaustedError`.
- This error is caught in `AgentService` → returns HTTP 429 with `{"error": {"code": "budget_exhausted"}}`.
- **Do not make the LLM call if budget is exhausted.** Check happens before `LLMClient.run_agent()`.

**Cost calculation:**
```python
# Rates for claude-sonnet-4-6 (update when Anthropic changes pricing)
INPUT_RATE_PER_1K = Decimal("0.003")
OUTPUT_RATE_PER_1K = Decimal("0.015")
cost_usd = (input_tokens / 1000 * INPUT_RATE_PER_1K) + (output_tokens / 1000 * OUTPUT_RATE_PER_1K)
```

Store the rate constants in `app/config.py` so they can be updated without code changes.

**Acceptance Criteria:**
1. When `cost_ledger.cost_usd >= daily_budget_usd`: request returns HTTP 429 with correct error code.
2. `record()` is called after every successful LLM response.
3. `record()` uses `ON CONFLICT (tenant_id, date) DO UPDATE SET cost_usd = cost_ledger.cost_usd + EXCLUDED.cost_usd` — no double-count.
4. Budget check for Tenant A does not affect Tenant B.
5. If Postgres write fails in `record()`, the error is logged but does not fail the request (best-effort accounting; reconciler will correct).

**Tests required:**
- `tests/test_cost_ledger.py` — budget exhausted path, record upsert idempotency, multi-tenant isolation.

---

### T11 · New Read Endpoints

**Owner:** Codex
**Priority:** P1
**Depends-on:** T07, T08
**Status:** pending

**Scope:**
Implement all read endpoints from `docs/spec.md §8`:
`GET /tickets`, `GET /tickets/{id}`, `GET /audit`, `GET /metrics/cost`,
`GET /agents`, `GET /eval/runs`.

**Files to CREATE (do not exist yet — create from scratch):**
- `app/routers/tickets.py`
- `app/routers/analytics.py`
- `app/routers/agents.py`
- `tests/test_endpoints.py`

**Files to MODIFY (must exist — read before editing):**
- `app/main.py` — include new routers

**Pagination:** All list endpoints use `?cursor=<ISO-timestamp>&limit=<int>` (keyset pagination
on `created_at`). Default limit 50, max 100.

**Response envelope (all endpoints):**
```json
{
  "data": [...],
  "cursor": "<ISO-timestamp of last item | null>",
  "total": null
}
```

**Error envelope (all endpoints):**
```json
{"error": {"code": "...", "message": "..."}}
```

**Acceptance Criteria:**
1. All endpoints enforce the role matrix from T07.
2. All list endpoints support cursor pagination.
3. All responses filtered by `tenant_id` (via RLS + application-level assertion).
4. `GET /tickets/{id}` returns HTTP 404 (not 403) for cross-tenant ticket IDs.
5. `GET /audit` returns entries newest-first.

**Tests required:**
- `tests/test_endpoints.py` — one test per endpoint: happy path, pagination, wrong role, cross-tenant.

---

### T12 · Agent Registry CRUD (`GET /agents`, `PUT /agents/{id}`)

**Owner:** Codex
**Priority:** P1
**Depends-on:** T11, T03
**Status:** pending

**Scope:**
Implement agent config read and update. Update creates a new versioned row and marks the old
one `is_current=FALSE`. Triggers `TenantRegistry.invalidate()` and an eval run (async).

**Files to CREATE (do not exist yet — create from scratch):**
- `app/agent_registry.py` — `AgentRegistryService`
- `tests/test_agent_registry.py`

**Files to MODIFY (must exist — read before editing):**
- `app/routers/agents.py` — add PUT handler (file created in T11)

**PUT /agents/{agent_id} behavior:**
1. Validate request body against `AgentConfigUpdate` Pydantic model.
2. Fetch current `agent_configs` row; verify `tenant_id` matches JWT.
3. `UPDATE agent_configs SET is_current=FALSE WHERE agent_config_id=$1`.
4. `INSERT agent_configs (new row with version+1, is_current=TRUE)`.
5. Invalidate `TenantRegistry` cache for tenant.
6. Emit `agent_config_updated` log event with old/new version.
7. Do NOT auto-trigger eval (eval is expensive; defer to `POST /eval/run`).

**Acceptance Criteria:**
1. `PUT /agents/{id}` increments version and sets old row `is_current=FALSE`.
2. Only `tenant_admin` role can call this endpoint.
3. Attempting to update another tenant's agent config → HTTP 404.
4. Response body is the new agent config row.

**Tests required:**
- `tests/test_agent_registry.py` — version bump, cross-tenant rejection, invalid payload.

---

## Phase 4 — Embeddings + RCA (Target: Week 3)

---

### T13 · EmbeddingService

**Owner:** Codex
**Priority:** P1
**Depends-on:** T08
**Status:** pending

**Scope:**
After every successful triage, generate a vector embedding of the ticket text and upsert it
into `ticket_embeddings`. This runs as a background task (fire-and-forget after response is sent).

**Files to CREATE (do not exist yet — create from scratch):**
- `app/embedding_service.py`
- `tests/test_embedding_service.py`

**Files to MODIFY (must exist — read before editing):**
- `app/agent.py` — add `asyncio.create_task(embedding_service.upsert(...))` after response
- `app/config.py` — add `voyage_api_key: str = ""`, `embedding_model: str = "voyage-3-lite"`

**Embedding model:**
Use Anthropic's `voyage-3` (or `voyage-3-lite`) via the Voyage AI API. Add `VOYAGE_API_KEY`
to settings. If unavailable, fall back to a deterministic SHA-256 mock vector (dev/test only).

**Upsert logic:**
```sql
INSERT INTO ticket_embeddings (ticket_id, tenant_id, embedding, model_version)
VALUES ($1, $2, $3, $4)
ON CONFLICT (ticket_id) DO UPDATE SET embedding=$3, model_version=$4, created_at=NOW();
```

**Acceptance Criteria:**
1. After `POST /webhook`, a row appears in `ticket_embeddings` within 5 seconds.
2. Embedding failure does not affect webhook response (fire-and-forget; error logged only).
3. `model_version` matches the Voyage model name used.
4. Embedding vector has correct dimension (1024 for voyage-3).

**Tests required:**
- `tests/test_embedding_service.py` — mock Voyage API; assert upsert called; assert fire-and-forget does not block response.

**Notes:**
- Changing embedding models requires re-embedding all existing tickets. Document this migration path in `docs/data-map.md §6` before changing models.
- `VECTOR(1024)` for voyage-3 vs `VECTOR(1536)` for text-embedding-3-small. Pick one model and pin it. Update the migration in T01 if needed.

---

### T14 · RCA Clusterer Background Job

**Owner:** Codex
**Priority:** P1
**Depends-on:** T13
**Status:** pending

**Scope:**
APScheduler job that runs every 15 minutes per active tenant. Clusters recent ticket embeddings
using pgvector ANN + DBSCAN, then summarizes each cluster with a single LLM call.

**Files to CREATE (do not exist yet — create from scratch):**
- `app/jobs/__init__.py` (empty)
- `app/jobs/rca_clusterer.py`
- `tests/test_rca_clusterer.py`

**Files to MODIFY (must exist — read before editing):**
- `app/main.py` — register APScheduler job in lifespan
- `app/config.py` — add `rca_lookback_hours: int = 24`, `rca_budget_per_run_usd: Decimal = Decimal("0.15")`

**Algorithm:**
```
1. SELECT ticket_id, embedding FROM ticket_embeddings
   WHERE tenant_id=$1 AND created_at > NOW() - INTERVAL '$2 hours'
   ORDER BY embedding <-> (SELECT AVG(embedding) FROM ticket_embeddings WHERE tenant_id=$1)
   LIMIT 500;
2. Build distance matrix (scipy or numpy cosine distance).
3. DBSCAN(eps=0.15, min_samples=3) — parameters per-tenant from agent_configs.guardrails.
4. For each cluster (max 50):
   a. Sample up to 5 ticket texts (raw_text, fetched with RLS-bypassing admin session).
   b. Call LLMClient.summarize_cluster(texts) — single call, no tool_use loop.
   c. UPSERT cluster_summaries.
5. Log rca_run_complete with duration, ticket_count, cluster_count.
```

**Cost control:**
Cap at 50 clusters. Each cluster costs ≈ $0.003. Max cost per RCA run = $0.15 per tenant.
At 10 tenants × 4 runs/hour = 40 runs/hour. Max cost = $6/hour. Enforce a separate
`rca_budget_per_run_usd` setting.

**Acceptance Criteria:**
1. Job runs every 15 minutes; verified by checking `gdev_rca_run_duration_seconds` metric.
2. DBSCAN output is capped at 50 clusters; excess logged as `rca_cluster_cap_hit`.
3. LLM summarize call uses a separate, simpler prompt (not the full triage tool_use prompt).
4. Cluster summaries accessible via `GET /clusters`.
5. RCA job uses `gdev_admin` DB role to bypass RLS (cluster summarization reads ticket text; the admin role is acceptable here because results are aggregated and pseudonymized before exposure).
6. If Anthropic API fails during summarize: use generic label "Cluster {n}"; log warning; continue.
7. Job timeout: `asyncio.wait_for(rca_run(), timeout=300)` — cancel and log if exceeded.

**Tests required:**
- `tests/test_rca_clusterer.py` — mock embeddings; verify DBSCAN call; verify LLM summarize call; verify cluster cap; verify timeout cancellation.

**Notes:**
- Step 4a fetches `raw_text` — this is the only place `gdev_admin` role is used at runtime.
  The admin role bypasses RLS; ensure the query is scoped by `WHERE tenant_id=$1` in application code.
  This is a risk: a bug in this query could leak cross-tenant ticket text into the cluster summary.
  Add an explicit `assert cluster_tenant_id == expected_tenant_id` check before the LLM call.

---

### T15 · Cluster API Endpoints (`GET /clusters`, `GET /clusters/{id}`)

**Owner:** Codex
**Priority:** P1
**Depends-on:** T14, T11
**Status:** pending

**Scope:**
Implement cluster read endpoints. Clusters are RLS-scoped. Support filtering by `?is_active=true`
and `?severity=high`.

**Acceptance Criteria:**
1. Returns only active clusters for the requesting tenant.
2. `GET /clusters/{id}` includes a list of up to 10 member ticket IDs.
3. `viewer` role can access; no cost/audit data exposed.
4. Cross-tenant cluster ID → HTTP 404.

**Tests required:**
- `tests/test_endpoints.py` — extend with cluster endpoints.

---

## Phase 5 — Observability (Target: Week 4)

---

### T16 · OpenTelemetry Trace Instrumentation

**Owner:** Codex
**Priority:** P1
**Depends-on:** T08
**Status:** pending

**Scope:**
Wire OTel spans throughout the agent pipeline as defined in `docs/observability.md §3`.

**Files to modify:**
- `app/agent.py` — wrap each pipeline stage in a child span
- `app/llm_client.py` — span per LLM API call with token count attributes
- `app/middleware/auth.py`, `app/middleware/signature.py` — middleware spans
- `app/main.py` — configure `TracerProvider` in lifespan; OTLP exporter to `OTLP_ENDPOINT`
- `app/config.py` — add `otlp_endpoint: str = ""`, `otel_service_name: str = "gdev-agent"`

**Span requirements (per `docs/observability.md §3.1`):**
```python
with tracer.start_as_current_span("agent.input_guard") as span:
    span.set_attribute("text_length", len(text))
    span.set_attribute("tenant_id_hash", sha256(tenant_id))
    # ... guard logic ...
    span.set_attribute("blocked", False)
```

**No PII in spans:** `tenant_id` is always SHA-256 hashed before use as a span attribute.
`raw_text` never appears in any attribute. `user_id` is always `user_id_hash`.

**Trace propagation:** Extract `traceparent` W3C header from incoming requests. If absent,
generate a new root span. Inject `trace_id` and `span_id` into every log record.

**Acceptance Criteria:**
1. A `POST /webhook` request produces a trace with spans: `http.request`, `agent.input_guard`, `agent.budget_check`, `agent.llm_classify`, `agent.propose_action`, `agent.output_guard`, `agent.route`.
2. `agent.llm_classify` span has attributes: `model`, `input_tokens`, `output_tokens`, `cost_usd`, `turns_used`.
3. No PII in any span attribute (verified by output guard canary test adapted for spans).
4. `trace_id` appears in every log record from that request.
5. If `OTLP_ENDPOINT` is empty, traces are logged to stdout in dev mode only.

**Tests required:**
- `tests/test_observability.py` — use `opentelemetry-sdk` in-memory exporter; assert span names and attributes.

---

### T17 · Prometheus Metrics

**Owner:** Codex
**Priority:** P1
**Depends-on:** T16
**Status:** pending

**Scope:**
Register all Prometheus metrics from `docs/observability.md §2`. Expose `/metrics` endpoint.

**Files to CREATE (do not exist yet — create from scratch):**
- `app/metrics.py` — define all counters, histograms, gauges
- `tests/test_metrics.py`

**Files to MODIFY (must exist — read before editing):**
- `app/agent.py` — increment counters/histograms at appropriate points
- `app/main.py` — add `GET /metrics` endpoint (Prometheus scrape target)

**All metrics must include `tenant_hash` label** (SHA-256 of tenant_id). This provides
per-tenant visibility without exposing raw UUIDs in the metrics endpoint.

**`gdev_approval_queue_depth` gauge:**
This is non-trivial. Do not use Redis SCAN. Instead, maintain a counter:
- Increment on `ApprovalStore.put_pending()`.
- Decrement on `ApprovalStore.pop_pending()` (both approve and reject paths).
- Reset to 0 on startup (Redis may have stale pendng items; accept this inaccuracy at startup).

**Acceptance Criteria:**
1. `GET /metrics` returns valid Prometheus text format.
2. All metrics from `docs/observability.md §2` are present.
3. After one `POST /webhook`, `gdev_requests_total` counter increments.
4. After one LLM call, `gdev_llm_tokens_total` (input and output) increment.
5. `gdev_budget_utilization_ratio` gauge reflects current day spend / budget.

**Tests required:**
- `tests/test_metrics.py` — use prometheus_client's `REGISTRY.get_sample_value()` to assert metric values.

---

### T18 · Grafana Dashboard Definition

**Owner:** Human (Codex drafts JSON)
**Priority:** P2
**Depends-on:** T17
**Status:** pending

**Scope:**
Produce a Grafana dashboard JSON (provisioned via `docker/grafana/provisioning/dashboards/`) that covers the demo-critical panels.

**Required panels:**
1. Request rate (RPS) — by tenant_hash and status
2. LLM latency p50/p95 histogram
3. LLM cost (cumulative USD per tenant per day)
4. Budget utilization gauge (per tenant)
5. Guard block rate (input + output)
6. Pending queue depth
7. Override rate (from approval_events query via Postgres datasource)
8. RCA cluster count (active, per tenant)
9. Error rate (5xx)

**Files to create:**
- `docker/grafana/provisioning/dashboards/gdev-agent.json`
- `docker/grafana/provisioning/datasources/prometheus.yaml`
- `docker/grafana/provisioning/datasources/postgres.yaml` (for override rate panel)

**Acceptance Criteria:**
1. Dashboard loads in Grafana without errors after `docker compose up`.
2. All 9 panels render with data after running Scenario A load test.
3. Budget utilization panel fires a visual alert at 80%.

**Notes:**
- Do not use Grafana Alerting in v1 — too complex to configure in Docker Compose. Use dashboard annotations + visual thresholds only.

---

## Phase 6 — Security Hardening (Target: Week 4–5)

---

### T19 · Fix Known Bugs from MEMORY.md

**Owner:** Codex
**Priority:** P0
**Depends-on:** T02
**Status:** pending

**Scope:**
Close all known bugs catalogued in project MEMORY.md that are not already addressed by other tasks.

**Bug fixes:**

| Bug | Fix | File |
|---|---|---|
| N-2: `JsonFormatter` drops `exc_info` | Add `exc_info` serialization to `JsonFormatter.format()` | `app/logging.py` |
| Dead config `rate_limit_burst=3` never enforced | Implement burst enforcement in `RateLimitMiddleware` using a token bucket or simply as a max count per window | `app/middleware/rate_limit.py` |
| Double Settings/Redis at module load | Already addressed by T02 pattern (lazy factory) | `app/main.py` |
| Dead code in `pop_pending()` | Remove `self.redis.delete(key)` after GETDEL | `app/approval_store.py` |
| `asyncio.get_event_loop()` deprecated | Replace with `asyncio.get_running_loop()` | `app/agent.py` |
| Missing `Retry-After` header on 429 | Add `Retry-After: {window_seconds}` to RateLimitMiddleware 429 response | `app/middleware/rate_limit.py` |

**Acceptance Criteria:**
1. `exc_info` field is present and non-null in JSON log records for exception logs.
2. Burst limit (3 requests) triggers HTTP 429 within the rate window.
3. No `Settings()` or `redis.from_url()` at module import time.
4. `pop_pending()` calls GETDEL once; no subsequent DELETE.
5. `asyncio.get_running_loop()` used throughout.
6. HTTP 429 includes `Retry-After` header.

**Tests required:**
- `tests/test_logging.py` — exc_info in JSON.
- `tests/test_middleware.py` — burst limit, Retry-After header.

---

### T20 · Output Schema Validation for LLM Responses

**Owner:** Codex
**Priority:** P0
**Depends-on:** T08
**Status:** pending

**Scope:**
Every LLM tool call result must be validated against a strict Pydantic schema before it is
used. Currently, tool results are used as raw dicts. This is a hallucination vector.

**Files to modify:**
- `app/llm_client.py` — add schema validation after each tool result
- `app/schemas.py` — add Pydantic models for each tool result

**Tool result schemas:**
```python
class ClassifyToolResult(BaseModel):
    category: Literal["bug_report", "billing", "account_access",
                       "cheater_report", "gameplay_question", "other"]
    urgency: Literal["low", "medium", "high", "critical"]
    confidence: confloat(ge=0.0, le=1.0)

class ExtractToolResult(BaseModel):
    transaction_id: str | None = None
    error_code: str | None = None
    platform: str
    game_title: str | None = None
    reported_username: str | None = None
    keywords: list[str] = []

class CreateTicketToolResult(BaseModel):
    tool: Literal["create_ticket_and_reply", "escalate_to_human"]
    payload: dict
    risky: bool
    risk_reason: str | None = None
```

**Validation failure behavior:**
If a tool result fails Pydantic validation → log `llm_invalid_response`; force `risky=True`;
route to pending (do not crash). This catches model hallucinations in production without
breaking user experience.

**Acceptance Criteria:**
1. Invalid category string from LLM → request routes to pending; not 500.
2. `confidence` outside [0.0, 1.0] → clamped to range; logged.
3. Unknown tool name → force `escalate_to_human`; log `llm_unknown_tool`.
4. All existing tests pass.

**Tests required:**
- `tests/test_llm_client.py` — inject malformed tool responses; verify graceful degradation.

---

### T21 · HITL Postgres Persistence + Approval Events

**Owner:** Codex
**Priority:** P1
**Depends-on:** T08
**Status:** pending

**Scope:**
Currently `pending_decisions` exist only in Redis (expire silently). Per the spec, every pending
decision must also have a permanent record in Postgres. Every approval/rejection must create an
`approval_events` row.

**Files to modify:**
- `app/approval_store.py` — add Postgres write alongside Redis write
- `app/agent.py` — write `approval_events` row in `handle_approve()`

**`put_pending()` dual-write:**
```
1. Redis SETEX pending:{tenant_id}:{pending_id} → short-lived (TTL)
2. INSERT pending_decisions → permanent Postgres record
```

Both writes should succeed; if Postgres fails, raise (Redis-only is insufficient for audit).

**`pop_pending()` + approval:**
```
1. Redis GETDEL → atomic (idempotency guard)
2. INSERT approval_events (reviewer_hash, decision, latency_ms)
3. UPDATE pending_decisions SET resolved_at=NOW(), decision=$1
```

If Redis GETDEL returns None (expired/already-consumed) → HTTP 404. Do NOT write `approval_events`.

**Acceptance Criteria:**
1. After `put_pending()`, a row exists in `pending_decisions`.
2. After `POST /approve`, a row exists in `approval_events` with `reviewer_hash` and `decision`.
3. Double-approve: second `POST /approve` with same `pending_id` → HTTP 404; no second `approval_events` row.
4. Expired pending: after TTL, `pop_pending()` returns None → HTTP 404.

**Tests required:**
- `tests/test_approval_store.py` — extend with Postgres write assertions.

---

## Phase 7 — Eval Harness + Load Testing (Target: Week 5–6)

---

### T22 · Eval REST Endpoint + Per-Tenant Baseline

**Owner:** Codex
**Priority:** P1
**Depends-on:** T08, T10
**Status:** pending

**Scope:**
Implement `POST /eval/run` (triggers eval) and `GET /eval/runs` (list history).
Per-tenant baseline: store F1 score of the first eval run; subsequent runs alert if F1 drops > 0.02.

**Files to CREATE (do not exist yet — create from scratch):**
- `app/routers/eval.py`
- `tests/test_eval.py`

**Files to MODIFY (must exist — read before editing):**
- `eval/runner.py` — add `db_session` parameter; write `EvalRun` to Postgres
- `app/main.py` — include eval router

**Eval run isolation:**
In eval mode, set a flag that suppresses writes to `tickets` table and skips Linear/Telegram.
Cost is still tracked in `cost_ledger` under `category="eval"`.

**Regression detection:**
```python
prior_run = await db.execute(
    "SELECT accuracy_f1 FROM eval_runs WHERE tenant_id=$1 ORDER BY created_at DESC LIMIT 1"
)
if prior_run and current_f1 < prior_run.accuracy_f1 - 0.02:
    eval_run.regression_alert = True
    logger.warning("eval_regression_detected", ...)
```

**Acceptance Criteria:**
1. `POST /eval/run` → triggers eval asynchronously; returns `eval_run_id`.
2. `GET /eval/runs` lists runs for the tenant, newest first.
3. Regression alert set correctly when F1 drops > 0.02.
4. Eval run does not write tickets to the tickets table.
5. Eval cost tracked in cost_ledger.

**Tests required:**
- `tests/test_eval.py` — mock LLM; verify eval run created; verify regression detection.

---

### T23 · Locust Load Test Harness

**Owner:** Codex
**Priority:** P1
**Depends-on:** T11
**Status:** pending

**Scope:**
Implement the Locust load test harness from `docs/load-profile.md`.

**Files to create:**
- `load_tests/locustfile.py`
- `load_tests/scenarios/burst.py` — Scenario A
- `load_tests/scenarios/steady.py` — Scenario B
- `load_tests/fixtures/sample_messages.jsonl` — 50 synthetic player messages

**Locust structure:**
```python
# burst.py
class BurstUser(HttpUser):
    wait_time = between(0.016, 0.02)  # ~60 RPS at 60 users

    @task(8)
    def post_webhook(self):
        msg = random.choice(SAMPLE_MESSAGES)
        self.client.post("/webhook",
            headers={"X-Tenant-Slug": "test-tenant-a",
                     "X-Hub-Signature-256": hmac_sign(msg)},
            json=msg
        )

    @task(1)
    def post_approve(self): ...

    @task(1)
    def get_tickets(self): ...
```

**KPI assertions (CI check, not Locust built-in):**
Write a Python script `load_tests/check_kpis.py` that reads Locust CSV output and asserts:
- p50 < 2000 ms, p99 < 8000 ms, 5xx rate < 1%.
- Exit code 1 if any KPI fails. CI pipeline runs this after the load test.

**Acceptance Criteria:**
1. `locust -f load_tests/locustfile.py --headless --scenario burst --run-time 2m` runs without crash.
2. Against a running local stack (`docker compose up`), Scenario A KPIs pass.
3. `load_tests/check_kpis.py` exits 0 on a passing run, 1 on failure.
4. `load_tests/results/` directory populated with CSV + HTML report.

**Tests required:**
- `tests/test_load_test_fixtures.py` — verify `sample_messages.jsonl` parses correctly; verify HMAC signing utility works.

---

### T24 · Docker Compose Full Stack Update

**Owner:** Codex
**Priority:** P1
**Depends-on:** T01, T16, T17, T18
**Status:** pending

**Scope:**
Update `docker-compose.yml` to include Postgres (pgvector), Grafana, Prometheus, Loki, Tempo.
Add health checks and startup ordering.

**Services to add:**
```yaml
postgres:
  image: pgvector/pgvector:pg16
  environment: [POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD]
  healthcheck: pg_isready

prometheus:
  image: prom/prometheus:v2.50.0
  volumes: [./docker/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml]

grafana:
  image: grafana/grafana:10.3.0
  volumes: [./docker/grafana/provisioning:/etc/grafana/provisioning]
  depends_on: [prometheus]

tempo:
  image: grafana/tempo:2.4.0
  volumes: [./docker/tempo/tempo.yaml:/etc/tempo.yaml]

loki:
  image: grafana/loki:2.9.0
```

**Seed migration:**
Add `docker/seed.sql` that creates two test tenants with known webhook secrets for demo use.
Run via `docker compose run --rm migrate` service.

**Acceptance Criteria:**
1. `docker compose up -d` starts all services; `docker compose ps` shows all healthy.
2. `alembic upgrade head` runs successfully against the Docker Postgres.
3. Grafana dashboard loads at `http://localhost:3000`.
4. `POST /health` returns 200.

---

## Dependency Graph Summary

```
T01 ──► T02 ──► T03 ──► T04
                  │         │
                  ▼         ▼
                 T05 ──► T06
                  │
                  ▼
                 T07 ──► T09
                  │
                  ▼
                 T08 ──► T10
                          │
              T11 ◄────────┘
               │
          T12 ─┤
          T13 ─┤── T14 ──► T15
          T16 ─┤
          T17 ─┤── T18
          T19 ─┘
          T20 ──► T21
          T22 ──► T23 ──► T24
```

---

## Success Metrics ("Done" for the Platform)

| Metric | Target | Verification |
|---|---|---|
| Tenant isolation | Zero cross-tenant rows returned | T09 test always passes |
| Classification F1 | ≥ 0.85 | Eval run on 2 tenants |
| Guard block rate | 1.00 on adversarial set | Existing eval cases |
| Webhook p99 latency | < 3 s | Locust Scenario A |
| Budget enforcement | Requests blocked at 100% budget | T10 test |
| Cost per request | < $0.015 | Locust Scenario B CSV |
| Grafana dashboard | All 9 panels render | Manual demo check |
| HITL approval audit | Every decision in Postgres | T21 test |
| RLS enforcement | Cannot be bypassed via API | T07, T09 tests |
