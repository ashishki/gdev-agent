# Phase 1 Review — Storage Foundation

_Reviewer: Senior Backend Engineer / Architect · Date: 2026-03-03_
_Scope: T01 (Alembic + initial schema), T02 (async DB engine + session), T03 (TenantRegistry)_

---

## Executive Summary

Phase 1 delivers a solid structural foundation: 16-table migration with RLS, async SQLAlchemy engine,
and a Redis-backed TenantRegistry. Three critical defects block Phase 2 start. The most severe is
P1-01 — synchronous Redis calls inside async methods in `TenantRegistry`, which will block the uvicorn
event loop under any real load. P1-03 is a security gap: `gdev_admin` is created without `BYPASSRLS`,
making all future admin-role migration steps unsafe. P1-02 is a correctness defect in `make_engine()`
that crashes on any SQLite test URL when the engine is instantiated without mocking. Four non-critical
issues and several doc-drift items are recorded below. **Verdict: No-Go for T05.**

---

## Critical Issues (must fix before T05 ships)

---

### P1-01 · Synchronous Redis client blocks the event loop in TenantRegistry

**File:** `app/tenant_registry.py:45`, `app/tenant_registry.py:91`, `app/tenant_registry.py:95`

**What is wrong:**
`TenantRegistry.get_tenant_config()` and `invalidate()` are declared `async def`, but all three Redis
calls use the synchronous `redis.StrictRedis` client that is passed in from `app/main.py:92`:

```python
# app/main.py:68
redis_client = redis.from_url(settings.redis_url)          # sync client
# app/main.py:92
app.state.tenant_registry = TenantRegistry(redis_client, db_session_factory)
```

The three blocking calls:
```python
# tenant_registry.py:45
cached = self._redis.get(cache_key)         # blocks event loop on network I/O

# tenant_registry.py:91
self._redis.setex(cache_key, ...)           # blocks event loop

# tenant_registry.py:95
self._redis.delete(self._cache_key(...))    # blocks event loop
```

Each of these calls performs a synchronous TCP socket read/write on the event loop thread, stalling
all other coroutines for the duration of the Redis round-trip (typically 1–5 ms; worse under load or
network degradation). This violates uvicorn's async contract and will cause latency spikes across all
concurrent requests.

**Exact fix required:**
Create a dedicated async Redis client in the lifespan and pass it to `TenantRegistry`:

```python
# app/main.py — in lifespan, after line 68
import redis.asyncio as aioredis
async_redis_client = aioredis.from_url(settings.redis_url)
# app/main.py:92 — change to:
app.state.tenant_registry = TenantRegistry(async_redis_client, db_session_factory)
```

`TenantRegistry` requires no code changes — `redis.asyncio` exposes the same `.get()`, `.setex()`,
`.delete()` API, and when called from an `async def` they correctly `await` instead of blocking.

**Test that would catch it:**
An integration test using a real async Redis client (via testcontainers Redis) in an asyncio context.
A unit test using `AsyncMock` for Redis methods rather than a synchronous stub would also catch the
type mismatch at the Python level:

```python
# test would verify that redis stub methods are coroutines, not plain callables
redis_stub = AsyncMock()
registry = TenantRegistry(redis_stub, session_factory)
await registry.get_tenant_config(tenant_id)
redis_stub.get.assert_awaited_once()  # fails with current sync stub
```

**Task to fix in:** Assign to a new T00A task before T05, or fix in T05 pre-flight (T05 already
depends on TenantRegistry to resolve tenant context).

---

### P1-02 · `make_engine()` passes pool_size / max_overflow unconditionally — crashes on SQLite

**File:** `app/db.py:21–26`

**What is wrong:**
```python
return create_async_engine(
    database_url,
    pool_size=settings.db_pool_size,       # line 23 — unsupported by SQLite
    max_overflow=settings.db_max_overflow, # line 24 — unsupported by SQLite
    pool_pre_ping=True,
)
```

SQLAlchemy's async SQLite dialect (`sqlite+aiosqlite`) uses `StaticPool` (or `NullPool`) internally
and does not accept `pool_size` or `max_overflow`. Calling `make_engine()` with a SQLite URL
(e.g., `TEST_DATABASE_URL=sqlite+aiosqlite:///:memory:`) without mocking `create_async_engine`
raises:

```
ArgumentError: Invalid argument(s) 'pool_size','max_overflow' sent to create_engine()
call on dialect sqlite+aiosqlite.
```

This crash is invisible in `test_db.py` because `test_make_engine_uses_test_database_url` monkeypatches
`create_async_engine` away entirely. Future integration tests (T08, T09) that call `make_engine()`
directly against SQLite will fail at startup.

**Exact fix required:**
```python
# app/db.py — make_engine()
sqlite = database_url.startswith("sqlite")
kwargs = {"pool_pre_ping": True} if sqlite else {
    "pool_size": settings.db_pool_size,
    "max_overflow": settings.db_max_overflow,
    "pool_pre_ping": True,
}
return create_async_engine(database_url, **kwargs)
```

For SQLite, additionally pass `poolclass=StaticPool` and `connect_args={"check_same_thread": False}`.

**Test that would catch it:**
```python
def test_make_engine_sqlite_does_not_crash():
    # No monkeypatch — calls the real create_async_engine
    settings = Settings(test_database_url="sqlite+aiosqlite:///:memory:")
    engine = db.make_engine(settings)  # must not raise ArgumentError
    assert engine is not None
```

**Task to fix in:** T00A (same pre-T05 fix task as P1-01).

---

### P1-03 · `gdev_admin` role created without BYPASSRLS — admin queries subject to RLS

**File:** `alembic/versions/0001_initial_schema.py:367–370`

**What is wrong:**
```python
op.execute("CREATE ROLE gdev_admin NOINHERIT LOGIN")
op.execute("GRANT ALL ON ALL TABLES IN SCHEMA public TO gdev_admin")
```

`gdev_admin` is created with table-level `GRANT ALL` but without the `BYPASSRLS` attribute.
`docs/architecture.md §7` and `docs/data-map.md §6` both specify:
> "Migrations and admin operations use a separate gdev_admin user with BYPASSRLS."

Without `BYPASSRLS`, any connection running as `gdev_admin` is subject to the RLS policies on all
15 tenant-scoped tables. Since admin operations (e.g., background jobs in `app/jobs/`) do not set
`app.current_tenant_id` before querying, RLS will silently return zero rows (with `missing_ok=TRUE`)
rather than the intended cross-tenant view. This will cause silent data loss in aggregation jobs
(CostAggregator, RCAClusterer, EvalRunner) and in future admin migrations.

**Exact fix required:**
New migration `0002_grant_admin_bypassrls.py`:
```sql
-- upgrade()
ALTER ROLE gdev_admin BYPASSRLS;

-- downgrade()
ALTER ROLE gdev_admin NOBYPASSRLS;
```

This must be a new file — existing migration `0001` must NOT be edited (dev-standards §5.1 rule 3).

**Test that would catch it:**
An integration test that connects as `gdev_admin` and confirms a cross-tenant SELECT returns rows
from multiple tenants without setting `app.current_tenant_id`. Alternatively, `pg_roles.rolbypassrls`
can be checked:
```sql
SELECT rolbypassrls FROM pg_roles WHERE rolname = 'gdev_admin';  -- must be TRUE
```

**Task to fix in:** New migration task T00B. Can be combined with T00A into a single pre-T05 fix PR.

---

## Non-Critical Issues (fix in T00A/T00B or alongside next task)

---

### P1-04 · Dead parameter `session_factory` in `EventStore.__init__`

**File:** `app/store.py:19,22`; `app/main.py:80`

`EventStore.__init__` accepts `session_factory` and stores it as `self._session_factory`, but no
method in `store.py` ever reads `self._session_factory`. The `log_event()` method only uses
`self._conn` (SQLite). The parameter is also passed from `app/main.py:80`:
```python
store = EventStore(sqlite_path=settings.sqlite_log_path, session_factory=db_session_factory)
```
This is dead code. Its presence suggests an abandoned plan to migrate EventStore to Postgres via
SQLAlchemy. **Recommend:** remove `session_factory` from `__init__` and delete `self._session_factory`.
If Postgres persistence is desired in a future task, the parameter should be reintroduced when the
usage is also implemented. Fix in T00A (one-line diff).

---

### P1-05 · Redis URL (potentially containing credentials) surfaced in RuntimeError at startup

**File:** `app/main.py:72`

```python
raise RuntimeError(f"Redis unavailable at startup: {settings.redis_url}") from exc
```

`settings.redis_url` may be `redis://:secretpassword@redis-host:6379`. The full URL is included in
the RuntimeError message, which is typically captured by the process supervisor or container log
aggregator, exposing credentials in log storage. **Recommend:** remove the URL from the message:
```python
raise RuntimeError("Redis unavailable at startup") from exc
```
The `from exc` clause already attaches the low-level connection error (which does not include the
full credential string). Fix in T00A.

---

### P1-06 · `ticket_classifications.agent_config_id` lacks FK constraint

**File:** `alembic/versions/0001_initial_schema.py:166`

`docs/data-map.md §2` specifies:
```sql
agent_config_id UUID REFERENCES agent_configs(agent_config_id)
```
The migration defines:
```python
sa.Column("agent_config_id", postgresql.UUID(as_uuid=True), nullable=True),
```
No `sa.ForeignKey("agent_configs.agent_config_id")` is present. The column exists and is nullable,
so no crash occurs now, but orphaned `agent_config_id` values can be inserted without rejection at
the DB layer. This will cause a silent consistency hole once `agent_configs` rows are deleted. Since
existing migration files must not be edited, the fix is a new migration that adds the FK constraint:
```sql
ALTER TABLE ticket_classifications
  ADD CONSTRAINT fk_tc_agent_config
  FOREIGN KEY (agent_config_id) REFERENCES agent_configs(agent_config_id);
```
Defer to the next schema-touching task (likely T10 or first agent_configs usage). Not blocking T05.

---

## Test Coverage Gaps

| Gap | Why It Matters | Test to Add |
|-----|---------------|-------------|
| `make_engine()` with real SQLite URL (unmocked) | P1-02 is invisible without this; any future test infra using SQLite will fail at engine creation | `test_make_engine_sqlite_does_not_crash` — call real `db.make_engine()` with `test_database_url="sqlite+aiosqlite:///:memory:"` |
| Async Redis client in `TenantRegistry` unit tests | `_RedisStub` uses sync methods matching the actual sync client; P1-01 is completely invisible | Replace `_RedisStub` with `AsyncMock`; assert `redis.get.assert_awaited_once()` |
| `TenantRegistry` integration test against real async Redis | Unit tests with stubs cannot catch actual event loop blocking or serialization edge cases | Add `tests/test_tenant_registry_integration.py` using testcontainers Redis; mark `@pytest.mark.integration` |
| RLS cross-tenant read isolation in migration test | `test_migrations.py` only checks table existence; does not verify RLS blocks cross-tenant reads | Insert two tenants, set `app.current_tenant_id` to one, assert the other's rows are invisible (T09 scope, but gap noted) |
| `gdev_admin` BYPASSRLS attribute check | P1-03 is undetectable until a real cross-tenant admin query fails silently | Add assertion to migration test: `SELECT rolbypassrls FROM pg_roles WHERE rolname = 'gdev_admin'` must be `true` |

**Single most important missing test:** `test_make_engine_sqlite_does_not_crash` — this is the test
most likely to be added during T05 fixture setup, and without P1-02 fixed it will immediately break
any attempt to run integration tests with an in-memory SQLite database.

---

## Spec / Doc Drift

| Doc | Section | What Doc Says | What Code Does |
|-----|---------|--------------|----------------|
| `docs/architecture.md` §7, `docs/data-map.md` §6 | gdev_admin role | `gdev_admin` must have `BYPASSRLS` | Migration creates role without `BYPASSRLS` (`0001_initial_schema.py:368`) |
| `docs/data-map.md` §2 | `ticket_classifications` schema | `agent_config_id UUID REFERENCES agent_configs(agent_config_id)` | Migration omits FK constraint (`0001_initial_schema.py:166`) |
| `docs/data-map.md` §3 | Redis key for dedup | `{tenant_id}:dedup:{message_id}` (tenant-namespaced) | `app/dedup.py:17` uses `dedup:{message_id}` (no tenant prefix) |
| `docs/data-map.md` §3 | Redis key for pending | `{tenant_id}:pending:{pending_id}` (tenant-namespaced) | `app/approval_store.py:23` uses `pending:{pending_id}` (no tenant prefix) |
| `docs/data-map.md` §3 | Redis key for rate limit | `{tenant_id}:ratelimit:{user_id}`, type ZSET, sliding timestamps | `app/middleware/rate_limit.py:42` uses `ratelimit:{user_id}` (no tenant prefix), type STRING (INCR/EXPIRE) |
| `docs/ARCHITECTURE.md` §6.2 | Redis key for dedup | `dedup:{message_id}` (matches code) | `app/dedup.py:17` ✅ |

**Root cause of data-map drift:** `docs/data-map.md §3` describes the _intended_ multi-tenant Redis
key namespace (designed for a later phase), while `docs/ARCHITECTURE.md §6.2` documents the _current_
single-namespace implementation. These two docs contradict each other. ARCHITECTURE.md §6.2 matches
the code. **Recommend:** update `data-map.md §3` to reflect current key patterns, with a note that
tenant-namespaced Redis keys are a Phase 5 hardening item.

---

## Verdict

**No-Go for Phase 2 (T05) start.**

Blocking items:
- **P1-01** — synchronous Redis in async methods must be fixed before T05 depends on `TenantRegistry`
  for tenant context injection (T05's `JWTMiddleware` will call `registry.get_tenant_config()` on every
  request, making this a hot-path blocking call).
- **P1-02** — make_engine SQLite pool params must be fixed before test infra expands.
- **P1-03** — BYPASSRLS migration must ship before any background job (CostAggregator, RCAClusterer)
  uses the `gdev_admin` connection.

Recommended: collect P1-01, P1-02, P1-04, P1-05 into task T00A (code fixes, no schema change).
Collect P1-03 into task T00B (new Alembic migration `0002_grant_admin_bypassrls.py`). Both tasks
are small and can ship as a single PR before T05 begins.
