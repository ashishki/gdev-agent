# 2026-03-03 — Phase 1 Storage Foundation (T01–T03)

**Type:** architecture
**Severity:** low (planned implementation; no production traffic)
**Affected components:** alembic migrations, SQLAlchemy engine, TenantRegistry, SignatureMiddleware (pending T04)
**Affected tenants:** none (dev only — no production deployment yet)
**Discovered by:** implementation session (Codex + human review)
**Reporter:** automated + architecture review

---

## What Changed

T01–T03 added the storage foundation for multi-tenant operation:
- Alembic async migration system (16 tables, RLS, two DB roles)
- Async SQLAlchemy engine + session factory with per-request `SET LOCAL` tenant context
- TenantRegistry: Redis-cached (TTL 300 s) tenant config backed by Postgres

---

## Bugs Found and Fixed During Implementation

### Bug 1 — Pydantic `PostgresDsn` strips `+asyncpg` driver suffix

**Severity:** high (would silently break async DB connections in production)

**Symptom:** `str(settings.database_url)` returned `postgresql://...` instead of
`postgresql+asyncpg://...`. SQLAlchemy then selected the psycopg2 sync driver,
causing the async engine to fail or fall back incorrectly.

**Root cause:** `pydantic.PostgresDsn` normalises the URL scheme and strips the
driver suffix (e.g. `+asyncpg`). Any code that passes `settings.database_url`
through Pydantic validation loses the driver information.

**Fix:** `alembic/env.py` reads `DATABASE_URL` directly from `os.environ` (bypassing
`get_settings()`). `make_engine()` in `app/db.py` uses `settings.test_database_url`
(plain `str`) first, falling back to `str(settings.database_url)` only when no
test URL is configured.

**Do not revert:** Any future code that uses `settings.database_url` as an engine URL
must call `str(settings.database_url)` and verify the driver suffix is present.
Prefer passing the raw env var string where possible.

---

### Bug 2 — `async_engine_from_config` ignores in-memory URL override

**Symptom:** Even after fixing Bug 1, using `async_engine_from_config(config.get_section(...))`
in `alembic/env.py` caused the engine to fall back to the `alembic.ini` file on disk,
which has no `sqlalchemy.url` entry. The psycopg2 driver was selected.

**Root cause:** `config.set_main_option("sqlalchemy.url", url)` sets the URL in memory,
but `config.get_section(config.config_ini_section)` returns a copy of the INI section
without the in-memory override applied.

**Fix:** Use `create_async_engine(_database_url, poolclass=pool.NullPool)` directly
in `run_migrations_online()`. Never use `async_engine_from_config` in this codebase.

---

### Bug 3 — `DROP ROLE` fails in downgrade when `alembic_version` holds grants

**Symptom:** `alembic downgrade base` raised
`role "gdev_app" cannot be dropped because some objects depend on it — privileges for table alembic_version`.

**Root cause:** The `upgrade()` function grants `gdev_app` privileges on
`ALL TABLES IN SCHEMA public`, which includes the `alembic_version` table
(created and managed by Alembic itself, not by our migration). When `downgrade()`
drops our tables and then attempts `DROP ROLE`, `alembic_version` still exists
and still holds the grant.

**Fix:** Added to `downgrade()`:
```sql
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gdev_app') THEN
        REVOKE ALL ON ALL TABLES IN SCHEMA public FROM gdev_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gdev_admin') THEN
        REVOKE ALL ON ALL TABLES IN SCHEMA public FROM gdev_admin;
    END IF;
END
$$;
```
The `IF EXISTS` guard is required because `downgrade base` on a fresh database
(where the roles were never created) must not fail.

---

### Bug 4 — testcontainers returns `postgresql+psycopg2://` not `postgresql://`

**Symptom:** `PostgresContainer.get_connection_url()` returns
`postgresql+psycopg2://test:test@localhost:PORT/test`. The test code was replacing
`"postgresql://"` with `"postgresql+asyncpg://"`, which did not match.

**Fix:** Use `re.sub(r"^postgresql(\+\w+)?://", "postgresql+asyncpg://", sync_url)`
to normalise any driver-aware URL from testcontainers.

**Applies to:** all future integration tests that receive URLs from testcontainers.

---

### Bug 5 — pgvector extension creation fails in dev environments

**Symptom:** `CREATE EXTENSION IF NOT EXISTS vector` fails with
`ERROR: could not open extension control file ".../vector.control": No such file or directory`
on Postgres instances without the pgvector package installed.

**Fix:** Check `pg_available_extensions` before creating the extension.
If `vector` is not available, the `ticket_embeddings.embedding` column falls back to `TEXT`.
This is intentional for dev. Production must use `pgvector/pgvector:pg16` or equivalent.

---

### Bug 6 — `sg docker -c "..."` env breaks pytest `tmp_path` fixture

**Symptom:** Running tests as `sg docker -c ".venv/bin/pytest tests/ -x -q"` produced
`FileNotFoundError: No usable temporary directory found` at pytest startup.

**Root cause:** `sg` (newgrp) spawns a subshell that inherits a restricted `$TMPDIR`
from the docker socket environment. pytest cannot create its temp directory.

**Fix:** Never run tests via `sg docker -c "..."`. Run directly:
```
.venv/bin/pytest tests/ -q --ignore=tests/test_migrations.py
```
Migration tests (which need Docker) are run separately or skipped automatically
when Docker is unavailable (the test has three fallback paths).

---

## What Changed in Architecture or Documentation

- `docs/ARCHITECTURE.md` §2.1: added T01–T03 components to component status table
- `docs/ARCHITECTURE.md` §2.2: added `alembic/`, `app/db.py`, `app/tenant_registry.py` to repo layout
- `docs/ARCHITECTURE.md` §6.2: added `tenant:{tenant_id}:config` and `jwt:blocklist:{jti}` to Redis key table
- `docs/data-map.md` §3: corrected key pattern from `{tenant_id}:config` to `tenant:{tenant_id}:config`
- `docs/tasks.md`: T01, T02, T03 marked `done`
- `docs/CODEX_PROMPT.md`: → v2.3; SESSION HANDOFF updated with T01–T03 output and T04 handoff

---

## What Was Learned

1. **Never trust Pydantic to preserve driver suffixes in DSN fields.** Always use
   `os.environ.get("DATABASE_URL")` directly in infrastructure code (migrations, engine
   factory). The Pydantic model is for validation only, not for URL round-tripping.

2. **`GRANT ALL ON ALL TABLES` is broader than it appears.** It includes Alembic's own
   internal tables. Any migration that grants role privileges must also include a revoke
   in the corresponding downgrade.

3. **testcontainers URL format is not stable.** Do not assume `postgresql://` prefix.
   Always normalise with a regex before passing to asyncpg.

4. **Running tests inside `sg docker`** changes the process environment in unexpected ways.
   Keep test invocation simple and direct.

---

## Follow-up Actions

| Action | Owner | Status |
|---|---|---|
| T04 — per-tenant HMAC secret lookup | Codex | open |
| Fix `test_middleware.py::test_correct_signature_passes` (`data=` → `content=`) | Codex (in T04) | open |
| Add HNSW index creation note to data-map.md (when pgvector is confirmed in prod) | Architecture | open |

---

**Closed:** open (T04 in progress)
