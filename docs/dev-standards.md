# gdev-agent — Development Standards v1.0

_Owner: Architecture · Date: 2026-03-03_
_These standards govern all code produced by Codex or human engineers for this repository._
_Non-compliance is grounds for PR rejection._

---

## 1. Repository Conventions

### 1.1 Directory Structure

```
gdev-agent/
├── alembic/                    # Alembic migration files only
│   ├── versions/               # One file per migration; sequential ID prefix
│   └── env.py                  # Async SQLAlchemy env; reads DATABASE_URL from settings
├── app/
│   ├── routers/                # FastAPI route handlers; one file per domain
│   ├── middleware/             # Starlette middleware classes
│   ├── guardrails/             # Input and output guard logic
│   ├── integrations/           # External API clients (Linear, Telegram, Voyage)
│   ├── jobs/                   # APScheduler background jobs
│   ├── prompts/                # LLM prompt files; one subdirectory per agent
│   │   └── triage/
│   │       └── v1.0.txt
│   ├── schemas.py              # All Pydantic models; single file unless > 500 lines
│   ├── config.py               # Pydantic Settings; lru_cache; no other config source
│   ├── db.py                   # Engine, session factory, get_db_session dependency
│   ├── metrics.py              # All Prometheus metric definitions (single source of truth)
│   └── main.py                 # FastAPI app, lifespan, middleware registration
├── docs/                       # Architecture, spec, ADRs, task graph, standards
├── eval/                       # Evaluation harness and datasets
├── load_tests/                 # Locust files and fixtures
├── tests/                      # Pytest tests; mirror app/ directory structure
│   ├── conftest.py             # Shared fixtures: test DB, mock clients, test tenant
│   └── ...
├── docker/                     # Compose configs, Grafana, Prometheus, Tempo configs
└── .env.example                # All environment variables with descriptions; no defaults for secrets
```

### 1.2 What Goes Where

- **Business logic** → `app/` modules (not in route handlers).
- **Route handlers** → `app/routers/`. Handlers call services; they do not contain logic.
- **Config** → `app/config.py` only. No `os.environ` outside of config. No hardcoded values.
- **Tests** → `tests/`. Mirror the `app/` structure. Test file = `test_{module_name}.py`.
- **Migrations** → `alembic/versions/`. One migration per PR. Never edit a committed migration.

---

## 2. Commit Discipline

### 2.1 Commit Scope

- One logical change per commit.
- A commit must not simultaneously change application code, test code, and docs. Split if needed.
- Exception: a single-line fix and its corresponding test change may be in one commit.

### 2.2 Commit Message Format

```
<type>(<scope>): <subject>

[optional body: why, not what]

[optional: Closes #<issue>]
```

**Types:** `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `perf`, `security`

**Examples:**
```
feat(cost_ledger): enforce per-tenant daily budget before LLM call
fix(middleware): add Retry-After header to rate-limit 429 responses
test(isolation): add cross-tenant RLS bypass integration test
security(auth): fail closed when Redis blocklist is unreachable
```

### 2.3 What Must NOT Appear in Commits

- Hardcoded secrets, API keys, or passwords.
- `TODO` comments without a task reference (`# TODO(T17): ...` is acceptable).
- Commented-out code. Delete it.
- Changes to committed Alembic migration files.
- `print()` statements in application code.

### 2.4 Pre-commit Checks (Codex must run before reporting a task done)

```bash
# Run the full check suite before declaring a task complete
ruff check app/ tests/          # linting
ruff format --check app/ tests/ # formatting
mypy app/                       # type checking
pytest tests/ -x -q             # unit tests (fast)
git grep -rn "sk-ant\|lin_api_\|AKIA\|Bearer " app/  # secret scan; must return nothing
```

---

## 3. Code Style

### 3.1 General Rules

- Python 3.11+. Use `from __future__ import annotations` in all files.
- Line length: 100 characters (`ruff` enforced).
- Type annotations on all public function signatures. No `Any` without a comment explaining why.
- `ruff` for lint and format. Config in `pyproject.toml`. No separate `.flake8`.

### 3.2 FastAPI Patterns

```python
# Route handlers: thin. Call a service. Return a response. No business logic.
@router.get("/tickets", response_model=TicketListResponse)
async def list_tickets(
    cursor: str | None = None,
    limit: int = Query(default=50, le=100),
    db: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_role("viewer")),
    request: Request = ...,
) -> TicketListResponse:
    return await ticket_service.list(
        tenant_id=request.state.tenant_id,
        cursor=cursor,
        limit=limit,
        db=db,
    )
```

```python
# Services: business logic. Accept primitives and sessions. Return domain objects.
# Never import `Request` into a service — services are testable without HTTP.
class TicketService:
    async def list(self, tenant_id: UUID, cursor: str | None,
                   limit: int, db: AsyncSession) -> TicketListResponse: ...
```

### 3.3 Async Rules

- All DB calls use `await`. No `asyncio.run()` inside request handlers.
- Background tasks use `asyncio.create_task()` or APScheduler. Not `threading.Thread`.
- Do NOT use `asyncio.get_event_loop()`. Use `asyncio.get_running_loop()` when needed.
- `asyncio.wait_for(coro, timeout=N)` on all external calls with unknown duration.

### 3.4 Error Handling

```python
# Prefer explicit typed exceptions.
class BudgetExhaustedError(Exception):
    def __init__(self, tenant_id: UUID, current_usd: Decimal, budget_usd: Decimal): ...

# Catch at the boundary (route handler or middleware). Never swallow exceptions silently.
try:
    await cost_ledger.check_budget(tenant_id, db)
except BudgetExhaustedError:
    raise HTTPException(status_code=429, detail={"code": "budget_exhausted"})
```

- Never use bare `except:` or `except Exception:` without logging `exc_info=True`.
- All `LOGGER.warning()` and `LOGGER.error()` calls include `exc_info=True` when there is an active exception.

### 3.5 Secrets and PII

- No raw `tenant_id` UUID in log fields. Use `tenant_id_hash = sha256(str(tenant_id))[:16]` (first 16 chars for readability; full hash for uniqueness).
- No `user_id`, `email`, `raw_text`, or any player-provided string in log fields. These go to the audit DB, not logs.
- No secrets in span attributes. The output guard canary test verifies this.
- Every log record that touches a tenant must include `tenant_id_hash`.

### 3.6 Database Queries

```python
# Use parameterized queries. Never string-format SQL.
# BAD:
await session.execute(text(f"SELECT * FROM tickets WHERE tenant_id = '{tenant_id}'"))
# GOOD:
await session.execute(text("SELECT * FROM tickets WHERE tenant_id = :tid"), {"tid": str(tenant_id)})
```

- All multi-step writes are in a single transaction (`async with session.begin()`).
- All SELECT queries for tenant-scoped data go through a session that has `SET LOCAL app.current_tenant_id` set (enforced by `get_db_session`).
- Admin queries that intentionally bypass RLS use the `gdev_admin` DB URL and must be in `app/jobs/` only.

---

## 4. Test Strategy

### 4.1 Test Types and Scope

| Type | Location | Scope | Speed | When Required |
|---|---|---|---|---|
| Unit | `tests/test_*.py` | Single function/class; all deps mocked | < 50 ms/test | Every PR |
| Integration | `tests/test_*_integration.py` | Real Postgres (testcontainers) | < 5 s/test | All DB-touching features |
| Contract | `tests/test_isolation.py` | Multi-tenant RLS | < 10 s | Every schema change |
| Eval | `eval/runner.py` | Real LLM (or mocked) | Variable | Every prompt/config change |
| Load | `load_tests/` | Full stack | Minutes | Phase 7 and before release |

### 4.2 Unit Test Rules

- All external services (LLM, Postgres, Redis, Linear, Telegram) are mocked.
- Use `pytest-asyncio` for async tests.
- Fixtures live in `tests/conftest.py`. Never define fixtures inside test files.
- Do not test implementation details. Test observable behavior.
- Coverage requirement: ≥ 80% on `app/`. This is a floor, not a goal.

```python
# conftest.py pattern
@pytest.fixture
def mock_llm_client(mocker) -> MagicMock:
    """Returns a mock LLMClient that returns a fixed TriageResult."""
    client = mocker.MagicMock(spec=LLMClient)
    client.run_agent.return_value = TriageResult(...)
    return client

@pytest.fixture
async def test_db(anyio_backend):
    """Spins up a real Postgres via testcontainers. Resets between tests."""
    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        engine = create_async_engine(pg.get_connection_url().replace("postgresql", "postgresql+asyncpg"))
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield engine
```

### 4.3 Integration Test Rules

- Integration tests are in files ending `_integration.py`.
- They use `testcontainers` to spin up real Postgres and Redis.
- They are NOT run in unit test CI. They run in a separate CI step (`pytest -m integration`).
- Mark with `@pytest.mark.integration`.

### 4.4 Cross-Tenant Isolation Test (T09)

This test is mandatory for every PR that touches:
- Middleware (auth, signature, rate limit)
- `app/store.py` or any DB query
- RLS policies

If the isolation test fails, the PR is blocked regardless of all other tests passing.

### 4.5 Mocking LLM Calls

In unit and integration tests, mock the Anthropic client at the boundary:
```python
# Mock at the transport layer, not deep in the LLM client
@pytest.fixture
def mock_anthropic(mocker):
    response = AnthropicMessage(...)  # fixed response with classify tool result
    mocker.patch("app.llm_client.anthropic.Anthropic.messages.create", return_value=response)
```

Never make real Anthropic API calls in tests. The eval harness is the only place real calls are made.

### 4.6 What Tests Must NOT Do

- Make real external API calls (Anthropic, Linear, Telegram, Voyage).
- Write to production Redis or Postgres.
- Sleep for more than 100 ms.
- Use `time.sleep()`. Use `pytest-anyio` timeouts.

### 4.7 CI Must Be Set Up in Phase 1

**Rule:** The GitHub Actions CI workflow (`.github/workflows/ci.yml`) must be created in Phase 1 of any project — at the same time as the first tests are written. It must not be deferred to a later phase.

**Required CI steps (minimum):**
1. Install dependencies
2. Lint (`ruff check`)
3. Format check (`ruff format --check`)
4. Run tests (`pytest -q`)

**Why Phase 1, not later:**

- If CI is added in Phase 12 (as happened in this project), 12 phases of commits have never been automatically verified. The badge in README is a lie. Errors accumulate silently.
- CI catches baseline drift: every commit that breaks a test is flagged immediately, not 3 months later.
- CI establishes the "green baseline" discipline from day one. Engineers cannot merge if tests fail.
- Setting up CI takes < 30 minutes. The cost of not having it is measured in hours of debugging regressions that a single CI run would have caught.

**Template (copy this into new projects — adjust service images as needed):**

```yaml
name: CI
on:
  push:
    branches: ["master", "main"]
  pull_request:
    branches: ["master", "main"]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.10"
          cache: "pip"
      - run: pip install -r requirements-dev.txt -e .
      - run: ruff check app/ tests/
      - run: ruff format --check app/ tests/
      - run: pytest tests/ -q --tb=short
```

**Note on dependency install:** Use `pip install -r requirements-dev.txt -e .`, not `pip install -e ".[dev]"`. The latter requires `extras_require` in `setup.cfg` / `pyproject.toml`. If those are absent, CI silently installs only the base package and fails mysteriously.

---

## 5. Migration Discipline

### 5.1 Rules

1. Every schema change requires an Alembic migration file. No exceptions.
2. Migrations are sequential. Never skip a version number.
3. Committed migration files are immutable. To fix a migration error, create a new migration.
4. Every migration must be reversible (`downgrade` function must undo `upgrade` completely).
5. Test `upgrade` + `downgrade` in CI (T01 tests cover this).

### 5.2 Migration File Naming

```
alembic/versions/
  0001_initial_schema.py
  0002_add_password_hash_to_tenant_users.py
  0003_add_pending_decisions_resolved_at.py
```

### 5.3 RLS Policies in Migrations

RLS policies are added in the migration that creates the table. If a policy changes, create a
new migration that `DROP POLICY ... CASCADE` and `CREATE POLICY ...`.

### 5.4 Dangerous Migrations

Migrations that `DROP COLUMN`, `DROP TABLE`, or rename columns must:
1. Be preceded by a PR that removes all application code references to the column.
2. Be run during a maintenance window in production.
3. Have a human-reviewed rollback plan.

---

## 6. Diff-Based Edit Protocol (for Codex)

Codex must not perform big-bang rewrites. All changes are incremental diffs.

### 6.1 Mandatory Sequence

```
1. Read the target file completely.
2. Read the relevant test file for that module.
3. Read the governing spec/ADR for the change.
4. Produce the smallest diff that satisfies the task's Acceptance Criteria.
5. Extend the existing test file (never delete tests without justification).
6. Run the pre-commit check suite.
7. Report: files changed, lines added/removed, tests added/modified, acceptance criteria verified.
```

### 6.2 What "Smallest Diff" Means

- Do not reformat code you did not modify.
- Do not rename variables unless the task explicitly requires it.
- Do not add docstrings or comments to unchanged functions.
- Do not refactor adjacent code.
- A bug fix touches only the buggy code and its test.

### 6.3 When to Read Before Writing

Always. There is no exception. If you cannot see the file, ask before writing.

### 6.4 Reporting Format

After completing a task, report:
```
Task: T05
Status: done
Files modified:
  app/middleware/auth.py (+87, -0)
  app/config.py (+3, -0)
  tests/test_auth.py (+52, -0)
Acceptance criteria:
  1. ✅ Valid JWT → request.state populated
  2. ✅ Expired JWT → HTTP 401
  3. ✅ Revoked JTI → HTTP 401
  4. ✅ Redis down → HTTP 503 (fail closed)
  5. ✅ /health exempt from JWT
  6. ✅ /webhook exempt from JWT
Tests: 6 new, 0 modified, 0 deleted. All pass.
Regressions: none (full test suite: 47 pass, 0 fail).
```

---

## 7. Adding Observability Hooks

Every new service method, background job, and route handler must include:

### 7.1 Trace Span

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

async def my_service_method(tenant_id: UUID, ...) -> ...:
    with tracer.start_as_current_span("service.method_name") as span:
        span.set_attribute("tenant_id_hash", sha256_short(tenant_id))
        span.set_attribute("input_param", safe_value)  # never PII
        try:
            result = await _do_work()
            span.set_attribute("outcome", "ok")
            return result
        except SomeError as e:
            span.record_exception(e)
            span.set_status(trace.StatusCode.ERROR, str(e))
            raise
```

### 7.2 Prometheus Metric Increment

```python
from app.metrics import MY_COUNTER, MY_HISTOGRAM
import time

start = time.monotonic()
MY_COUNTER.labels(tenant_hash=sha256_short(tenant_id), status="ok").inc()
MY_HISTOGRAM.labels(tenant_hash=sha256_short(tenant_id)).observe(time.monotonic() - start)
```

### 7.3 Structured Log Event

```python
LOGGER.info(
    "descriptive_event_name",
    extra={
        "event": "descriptive_event_name",
        "trace_id": current_trace_id(),
        "tenant_id_hash": sha256_short(tenant_id),
        "context": {
            "key": "value"  # operational context; no PII
        }
    }
)
```

### 7.4 Required Hooks Per Component Type

| Component | Span? | Counter? | Histogram? | Log event? |
|---|---|---|---|---|
| Route handler | Via middleware | Yes (request) | Yes (latency) | On error only |
| Service method | Yes | Yes (on key events) | Yes (latency) | Yes |
| Background job | Yes (root span) | Yes | Yes | Yes (on start/complete/error) |
| LLM call | Yes | Yes | Yes | Yes (per call) |
| DB query | No (SQLAlchemy auto-instruments) | No | No | On error only |
| Integration call | Yes | Yes (error counter) | Yes | On error |

---

## 8. Security Checklist (per PR)

Before marking any PR as ready for review, verify:

- [ ] No secrets in code, logs, or span attributes.
- [ ] All user-provided strings are validated before use (Pydantic model or explicit check).
- [ ] All DB queries are parameterized.
- [ ] All new endpoints enforce role requirements via `require_role()`.
- [ ] All new service calls include `tenant_id` and respect the RLS boundary.
- [ ] `GET /metrics` does not expose raw `tenant_id` values (use `tenant_hash`).
- [ ] No new `# noqa` suppression without a comment explaining why it's safe.
- [ ] `git grep -rn "sk-ant\|lin_api_\|AKIA\|Bearer " app/` returns nothing.
- [ ] Cross-tenant isolation test still passes.
- [ ] Output guard canary test still passes (`guard block rate = 1.0`).
