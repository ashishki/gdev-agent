# Codex Implementation Agent Prompt v3.1

_Owner: Architecture · Updated: 2026-03-08_
_Authoritative prompt for the Codex implementation agent. Bump version on contract changes._

═══════════════════════════════════════════════════════════════════════
SESSION HANDOFF — START HERE
═══════════════════════════════════════════════════════════════════════

**Completed:** T01 ✅ T02 ✅ T03 ✅ T04 ✅ T00A ✅ T00B ✅ T05 ✅ T06 ✅ T06B ✅ T07 ✅
              T08 ✅ T09 ✅ T10 ✅ T11 ✅ T12 ✅
              P0-1 ✅ P0-2 ✅ P1-2 ✅ P1-3 ✅ P1-4 ✅
              FIX-1 ✅ FIX-2 ✅ FIX-3 ✅ FIX-4 ✅ FIX-5 ✅

**Phase 4 queue:** T13 → T14 → T15 (implement sequentially, do not skip)
**After T15:** STOP — do not start T16. Review gate: user runs Cycle 4 audit.
**Baseline:** 111 pass, 12 skipped (integration tests skip without Docker/TEST_DATABASE_URL)

─── Fix Queue (resolve before Phase 4 queue) ────────────────────────
(empty — Cycle 3 produced no P0/P1 requiring code fixes before T13)

─── Open Findings (full detail: docs/audit/REVIEW_REPORT.md) ────────

🔴 P1-1 OPEN — ADR-003 mandates RS256; implementation uses HS256
  Decision required (architecture, not Codex).
  Files: app/config.py:45-46, app/middleware/auth.py, app/routers/auth.py, docs/adr/003-rbac-design.md

🟡 P2-1 OPEN — Redis keys not tenant-namespaced (Phase 5 hardening)
🟡 P2-6 OPEN — app/agent.py imports HTTPException from fastapi (layer violation, deferred)
🟡 P2-9 OPEN — _run_blocking() duplicated in store.py and agent.py (deferred)
🟡 P2-10 OPEN — get_settings() requires ANTHROPIC_API_KEY at import time; set in conftest.py

─── T13 · EmbeddingService ──────────────────────────────────────────

Files to CREATE: app/embedding_service.py, tests/test_embedding_service.py
Files to MODIFY: app/agent.py, app/config.py

Key requirements:
  - Voyage AI API (voyage-3-lite); SHA-256 mock vector in dev/test (VOYAGE_API_KEY absent)
  - VECTOR(1024); pin model in config.embedding_model
  - Upsert: ON CONFLICT (ticket_id) DO UPDATE embedding, model_version, created_at=NOW()
  - Fire-and-forget: asyncio.create_task() after response — failure must NOT affect /webhook
  - ANTHROPIC_API_KEY must be set before importing app.main in test files

─── T14 · RCA Clusterer Background Job ─────────────────────────────

Depends-on: T13
Files to CREATE: app/jobs/__init__.py, app/jobs/rca_clusterer.py, tests/test_rca_clusterer.py
Files to MODIFY: app/main.py (register APScheduler job), app/config.py (+rca_lookback_hours, +rca_budget_per_run_usd)

Key requirements:
  - APScheduler job every 15 min per active tenant
  - pgvector ANN + DBSCAN(eps=0.15, min_samples=3); cap at 50 clusters
  - LLMClient.summarize_cluster() — single call, no tool_use loop
  - gdev_admin role for raw_text fetch (bypasses RLS); MUST include WHERE tenant_id=$1
  - assert cluster_tenant_id == expected_tenant_id before LLM call
  - asyncio.wait_for(rca_run(), timeout=300)
  - On API failure: use "Cluster {n}" label, log warning, continue

─── T15 · Cluster API Endpoints ─────────────────────────────────────

Depends-on: T14, T11
Files to MODIFY: app/routers/ (new cluster router), app/main.py, tests/test_endpoints.py

Key requirements:
  - GET /clusters — viewer+ role; filter ?is_active=true / ?severity=high; RLS-scoped
  - GET /clusters/{id} — includes up to 10 member ticket_ids; cross-tenant → 404
  - No cost/audit data exposed to viewer role

─── STOP AFTER T15 ──────────────────────────────────────────────────

Do NOT start T16. After T15 report is complete, notify:
"Phase 4 complete (T13–T15). Ready for Cycle 4 review."

─── Implementation decisions Codex MUST NOT change ──────────────────

  A. alembic/env.py reads DATABASE_URL from os.environ (NOT get_settings()).
  B. create_async_engine() directly in make_engine() — NOT async_engine_from_config().
  C. downgrade() REVOKE block before DROP ROLE — keep it.
  D. pgvector extension conditional on pg_available_extensions — keep it.
  E. .venv at project root — use .venv/bin/pip install <pkg>.
  F. make_engine() checks test_database_url first (SQLite fallback for unit tests).
  G. get_db_session() uses session.begin() + SET LOCAL; skips SET when tenant_id=None.
     Never use session-level SET — leaks across connection pool.
  H. SignatureMiddleware reads body from ASGI receive, replays via replay_receive().
     Do NOT refactor to read from Request object.
  I. WebhookSecretStore does NOT cache secrets in Redis. This is intentional.

═══════════════════════════════════════════════════════════════════════
MANDATORY PRE-TASK PROTOCOL (skip no step)
═══════════════════════════════════════════════════════════════════════

Before writing a single line of code for any task, you must:

1. READ the task entry in docs/tasks.md completely.

2. For files listed under "Files to MODIFY": read each file before touching it.
   If a file listed as "to MODIFY" does not exist, STOP and report:
   "File not found: <path>. This file must exist before T## can proceed."

   For files listed under "Files to CREATE": these do not exist yet — that is expected.

3. READ docs/dev-standards.md completely (once per session).

4. READ the sections of docs/spec.md and docs/architecture.md relevant to the task.

5. READ docs/data-map.md if the task touches the database, Redis, or schema.

6. For each file listed under "Files to MODIFY", read the corresponding test file.

7. VERIFY the task's "Depends-On" chain: output files of those tasks must exist on disk.

If a Depends-On file is missing: STOP and report. Do not create stubs.

═══════════════════════════════════════════════════════════════════════
IMPLEMENTATION CONTRACT
═══════════════════════════════════════════════════════════════════════

── DIFF-BASED EDITS ──────────────────────────────────────────────────
- Produce the smallest diff that satisfies the Acceptance Criteria.
- Do not reformat code you did not logically modify.
- Do not add docstrings, comments, or type annotations to unchanged functions.
- Do not rename variables unless the task requires it.
- Do not refactor adjacent code.
- New files are created only when they appear under "Files to CREATE" in the task.

── SCHEMA VALIDATION ────────────────────────────────────────────────
- Every LLM tool result must be validated through a strict Pydantic model before use.
- Validation failure: log error, force risky=True, route to pending.
- All API request/response bodies use Pydantic models. No raw dicts.

── SECURITY REQUIREMENTS ────────────────────────────────────────────
- All database queries are parameterized. String interpolation in SQL is forbidden.
- Tenant isolation: every service method touching Postgres must receive tenant_id explicitly.
- Role enforcement: every new route handler must use require_role() dependency.
- JWT blocklist: fail CLOSED (HTTP 503) if Redis unavailable — never fail open.
- Approval path: pending.tenant_id verified against jwt.tenant_id via Postgres row.
- Secrets: `git grep -rn "sk-ant\|lin_api_\|AKIA\|Bearer " app/` must return zero results.
- PII: user_id, email, raw_text never in log fields, span attributes, or metric labels.
  Use SHA-256 hashed variants everywhere.

── DATABASE RULES ────────────────────────────────────────────────────
- Always use SET LOCAL app.current_tenant_id = :tid (not session-level SET).
- Admin queries (gdev_admin role) only in app/jobs/; must include WHERE tenant_id = :tid.
- Every schema change requires an Alembic migration. No exceptions.
- make_engine() must NOT pass pool_size/max_overflow when URL scheme starts with "sqlite".

── ASYNC CORRECTNESS ────────────────────────────────────────────────
- All Redis operations inside async def must use redis.asyncio client.
- Calling synchronous blocking I/O inside async def without asyncio.to_thread() is forbidden.

── OBSERVABILITY HOOKS ──────────────────────────────────────────────
Every new service method must include:
1. OTel child span: tracer.start_as_current_span("service.method_name")
   Attributes: tenant_id_hash (SHA-256 short). No PII. Record exceptions.
2. Prometheus counter on key outcome (success/error).
3. Prometheus histogram for operation latency.
4. Structured log on completion or error with exc_info=True on errors.

── MIGRATIONS ───────────────────────────────────────────────────────
- Migration file name: {NNNN}_{snake_case_description}.py
- Both upgrade() and downgrade() must be complete and correct.
- Never edit an existing migration. Create a new one.
- RLS policies included in the migration that creates the table.
- Use current_setting('app.current_tenant_id', TRUE) in RLS policies.

── TESTS ────────────────────────────────────────────────────────────
- Every new function, method, and route requires at least one test.
- Every Acceptance Criterion must have a corresponding test case.
- New test files: tests/test_{module_name}.py
- Integration tests: tests/test_{module_name}_integration.py
- External services mocked in unit tests. Real Postgres via testcontainers in integration tests.
- After writing tests: pytest tests/ -x -q — confirm all pass.
- Do not delete or modify existing passing tests.

── AGENT PIPELINE SAFETY ────────────────────────────────────────────
- create_ticket_and_reply may not be called on LLM turn 1.
- Budget check (CostLedger.check_budget()) must run BEFORE every LLM call.
- Output guard (OutputGuard.scan()) must run on EVERY LLM draft response.

═══════════════════════════════════════════════════════════════════════
TASK EXECUTION WORKFLOW
═══════════════════════════════════════════════════════════════════════

STEP 1: UNDERSTAND — state task ID, list files, confirm Depends-On chain.
STEP 2: READ — read every file to MODIFY + existing tests. Report conflicts; do not resolve silently.
STEP 3: PLAN — 3–5 bullets: what changes and why. Flag deviations from spec.
STEP 4: IMPLEMENT — diffs for existing files; new files from scratch. Run ruff after each file.
STEP 5: TEST — write tests, run pytest -x -q, run isolation test if auth/DB/middleware touched,
               run secrets scan.
STEP 6: REPORT — use exact format:

  Task: T##
  Status: done | blocked | partial
  Files created: <path> (N lines)
  Files modified: <path> (+N, -N)
  Acceptance criteria: 1. ✅/❌ <criterion>
  Tests: N new, N modified. All pass / N failing.
  Regressions: none | <description>
  Blockers (if any): <description>
  Next task recommended: T##

═══════════════════════════════════════════════════════════════════════
FORBIDDEN ACTIONS
═══════════════════════════════════════════════════════════════════════

NEVER:
- Stop work because a "Files to CREATE" file does not exist.
- Make a real Anthropic API call in tests.
- Write secrets, API keys, or passwords to any file.
- Use os.environ directly (use app.config.get_settings() only).
- Call asyncio.get_event_loop() (use asyncio.get_running_loop()).
- Use except: or except Exception: without LOGGER.error(..., exc_info=True).
- Edit an existing Alembic migration file.
- Use session-level SET app.current_tenant_id (use SET LOCAL always).
- Return raw player message text in any log field, span attribute, or metric label.
- Delete or modify existing passing tests without stating the reason.
- Bypass the cross-tenant isolation test.
- Call create_ticket_and_reply before a successful classify_ticket result.
- Make LLM calls without a preceding budget check.
- Skip the output guard on any LLM response.
- String-interpolate SQL queries.
- Accept unauthenticated requests on any endpoint except /health and /webhook.
- Swallow exceptions silently (no bare pass in except blocks).
- Create stub or placeholder files to satisfy dependency checks.

═══════════════════════════════════════════════════════════════════════
GOVERNING DOCUMENTS (read these; they are the contract)
═══════════════════════════════════════════════════════════════════════

docs/spec.md           — Product scope, SLAs, security assumptions, API surface
docs/ARCHITECTURE.md   — Component diagram, data flow, failure handling
docs/data-map.md       — All entities, schemas, Redis keys, RLS policies, PII rules
docs/tasks.md          — Task graph; your work queue
docs/dev-standards.md  — Code style, test strategy, commit discipline, observability hooks
docs/observability.md  — Metric names, span hierarchy, alerting strategy
docs/agent-registry.md — All agents, their tools, guardrails, and failure modes
docs/load-profile.md   — Load scenarios and KPIs
docs/adr/              — Architectural decisions; read before making structural choices
docs/audit/REVIEW_REPORT.md — Current open findings (P0/P1/P2)

If a task conflicts with any governing document, STOP and report the conflict.
Do not resolve conflicts silently. Architecture decides; Codex implements.
