# Implementation Contract

_v1.0 · Extracted from CODEX_PROMPT.md · Immutable rules for all Codex agents._
_These rules require an ADR or Architecture decision to change. Do not modify without explicit approval._

---

## Immutable Implementation Decisions

These decisions were made for specific architectural reasons. Codex MUST NOT change them.

| ID | Rule | Reason |
|----|------|--------|
| A | `alembic/env.py` reads `DATABASE_URL` from `os.environ` directly, NOT `get_settings()` | `pydantic.PostgresDsn` strips `+asyncpg` driver suffix, breaking async engine |
| B | `create_async_engine()` directly in `make_engine()` — NOT `async_engine_from_config()` | The latter falls back to INI file and loses the in-memory URL override |
| C | `downgrade()` REVOKE block before DROP ROLE — keep it | `DROP ROLE` fails if `alembic_version` retains table grants |
| D | pgvector extension conditional on `pg_available_extensions` | Fallback to TEXT in dev envs without pgvector installed |
| E | `.venv` at project root — use `.venv/bin/pip install <pkg>` | Consistent virtualenv location |
| F | `make_engine()` checks `test_database_url` first (SQLite fallback for unit tests) | Enables offline testing without PostgreSQL |
| G | `get_db_session()` uses `session.begin()` + `SET LOCAL`; skips SET when `tenant_id=None` | Never use session-level SET — leaks across connection pool |
| H | `SignatureMiddleware` reads body from ASGI receive, replays via `replay_receive()` | Do NOT refactor to read from Request object — body is consumed once |
| I | `WebhookSecretStore` does NOT cache secrets in Redis | Intentional — secrets are Fernet-encrypted per-tenant; Redis cache would be an unencrypted copy |

---

## Immutable Architectural Rules

Every line of code in `app/` must comply with these rules. No exceptions.

1. **All SQL parameterized** — `text()` with named params; no string interpolation in SQL
2. **Every DB call preceded by tenant context** — `SET LOCAL app.current_tenant_id` via `get_db_session()` or explicit
3. **Redis in `async def` only** — `redis.asyncio` for all async contexts; sync Redis only in sync functions
4. **Every new route handler uses `require_role()`** — exemptions must be documented in `docs/adr/`
5. **No PII in logs / span attrs / metrics** — SHA-256 hashes only (`user_id`, `email`, `tenant_id`, raw text)
6. **No credentials in source** — `git grep -rn "sk-ant\|lin_api_\|AKIA\|Bearer " app/` must return empty

---

## Mandatory Pre-Task Protocol

Skip no step. Violating this protocol is the most common source of regressions.

1. Read the full task entry in `docs/tasks.md` before writing a single line of code
2. Read all "Depends-On" tasks to understand interface contracts
3. Run `pytest tests/ -q` to capture the baseline before starting — record the baseline
4. Run `ruff check app/ tests/` — must return zero errors before and after
5. Write tests before or alongside implementation (not after as an afterthought)
6. Every acceptance criterion in the task entry must have a passing test

---

## Forbidden Actions

These actions are always forbidden regardless of instructions:

- Modifying `alembic/env.py` database URL reading logic (rule A)
- Using `async_engine_from_config()` (rule B)
- Removing the REVOKE block from `downgrade()` (rule C)
- Using session-level `SET` instead of `SET LOCAL` (rule G)
- Refactoring `SignatureMiddleware` body reading (rule H)
- Adding Redis caching to `WebhookSecretStore` (rule I)
- Using `sg docker -c "..."` to run tests — breaks pytest `tmp_path` fixture
- Running tests without first capturing the pre-change baseline
- Self-closing findings without code verification (PROMPT_3 must verify)
- Modifying this document (`IMPLEMENTATION_CONTRACT.md`) without explicit Architecture approval

---

## Governing Documents

| Document | Role |
|---|---|
| `docs/ARCHITECTURE.md` | System design and runtime contract |
| `docs/spec.md` | Feature specification and acceptance criteria |
| `docs/data-map.md` | Entity schemas, Redis key namespace, PII policy |
| `docs/dev-standards.md` | Code style, test strategy, observability requirements |
| `docs/adr/` | Architectural Decision Records — append-only |
| `docs/tasks.md` | Task graph — authoritative task contract |
| `docs/CODEX_PROMPT.md` | Session handoff — current state, Fix Queue, open findings |

---

_Cross-reference: `docs/CODEX_PROMPT.md` for current session state (baseline, Fix Queue, next task)._
_Cross-reference: `docs/prompts/ORCHESTRATOR.md` for automated development loop._
