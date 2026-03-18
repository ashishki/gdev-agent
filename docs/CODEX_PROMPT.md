# Codex Implementation Agent Prompt v3.10

_Owner: Architecture · Updated: 2026-03-18 (Cycle 9, Phase 8 complete)_
_Authoritative prompt for the Codex implementation agent. Bump version on contract changes._

═══════════════════════════════════════════════════════════════════════
SESSION HANDOFF — START HERE
═══════════════════════════════════════════════════════════════════════

**Completed:** T01 ✅ T02 ✅ T03 ✅ T04 ✅ T00A ✅ T00B ✅ T05 ✅ T06 ✅ T06B ✅ T07 ✅
              T08 ✅ T09 ✅ T10 ✅ T11 ✅ T12 ✅ T13 ✅ T14 ✅ T15 ✅ T16 ✅ T17 ✅ T18 ✅
              T19 ✅ T20 ✅ T21 ✅ T22 ✅ T23 ✅ T24 ✅
              P0-1 ✅ P0-2 ✅ P1-2 ✅ P1-3 ✅ P1-4 ✅
              FIX-1 ✅ FIX-2 ✅ FIX-3 ✅ FIX-4 ✅ FIX-5 ✅ FIX-6 ✅ FIX-7 ✅ FIX-8 ✅ FIX-9 ✅
              FIX-A ✅ FIX-B ✅ FIX-C ✅ FIX-D ✅ FIX-E ✅ FIX-F ✅ FIX-G ✅

**Baseline:** 168 pass, 13 skip — repo baseline green (`pytest tests/ -q`)
**Next task:** CLI-1 — Typer admin CLI (Phase 10 start)

─── Validation Snapshot ──────────────────────────────────────────────
✅ `pytest tests/ -q` → 168 passed, 13 skipped
✅ `ruff check app/ tests/`
✅ `ruff format --check app/ tests/`
✅ `mypy app/`

**Phase 5 queue:** T16 ✅ → T17 ✅ → T18 ✅
**Phase 6 queue:** T19 ✅ → T20 ✅ → T21 ✅
**Phase 7 queue:** T22 ✅ → T23 ✅ → T24 ✅
**Phase 8 queue:** FIX-A ✅ → FIX-B ✅ → FIX-C ✅ → FIX-D ✅ → FIX-E ✅ → FIX-F ✅
**Phase 9 queue:** FIX-G ✅ → SVC-1 ✅ → SVC-2 ✅ → SVC-3 ✅ → DOC-1 ✅ → DOC-2 ✅ → DOC-3 ✅
**Phase 10 queue:** CLI-1 [ ] → CLU-1 [ ] → CLU-2 [ ]
**Phase 11 queue:** PORT-1 [ ] → PORT-2 [ ] → PORT-3 [ ] → PORT-4 [ ]

─── Fix Queue ─── (empty — proceed to phase queue) ──────────────────
No P0 or P1 findings this cycle. Phase 8 complete. Proceed to Phase 9 queue.

─── Open Findings (full detail: docs/audit/REVIEW_REPORT.md) ────────

| ID | Sev | Status | Evidence / Note |
|----|-----|--------|-----------------|
| ARCH-1 | P1 | CLOSED | ADR/runtime aligned on HS256 (`app/config.py:49`, `docs/adr/003-rbac-design.md`) |
| CODE-3 | P2 | CLOSED | `tenant_id_hash` logging verified in `app/agent.py` |
| CODE-4 | P2 | CLOSED | Secrets scan clean; `Bearer ` literal removed from `app/` scope |
| CODE-5 | P2 | OPEN | Silent broad fallback exception in `_fetch_embeddings` — no `LOGGER.warning` (`app/jobs/rca_clusterer.py:276`) |
| CODE-6 | P2 | CLOSED | Negative cross-tenant test present (`tests/test_rca_clusterer.py:163`) |
| CODE-7 | P2 | CLOSED | Guarded `tool_choice` with empty tools fixed (`app/llm_client.py:288-294`) |
| CODE-8 | P3 | OPEN | RCA fallback exception branch lacks direct unit coverage (`tests/test_rca_clusterer.py`) |
| CODE-9 | P2 | CLOSED | Async `summarize_cluster_async` via `asyncio.to_thread` — FIX-C resolved |
| CODE-10 | P2 | OPEN | `run_blocking` raises untyped `data` — `raise data  # type: ignore[misc]` (`app/utils.py:34`) |
| CODE-11 | P2 | CLOSED | Redis hot-path keys tenant-namespaced — FIX-A resolved |
| CODE-12 | P2 | OPEN | Import-time `get_settings()` coupling may require API key at import (`app/main.py:223`) |
| CODE-13 | P2 | OPEN | `run_eval()` non-async path has no `check_budget()` call — budget bypass via CLI (`eval/runner.py:51-110`) |
| CODE-14 | P2 | CLOSED | Key prefix order inverted to `{tenant_id}:prefix:id` — FIX-G resolved |
| CODE-15 | P2 | OPEN | `auth_ratelimit:{email_hash}` has no tenant prefix — global by design but absent from data-map §3 (`app/middleware/rate_limit.py:129`) |
| CODE-16 | P2 | OPEN | `_fetch_raw_texts_admin` uses `gdev_admin` session with no tenant_id assertion (`app/jobs/rca_clusterer.py:427-440`) |
| ARCH-2 | P2 | CLOSED | ADR-002 updated to Voyage/1024-dim; migration 0004 confirmed correct — DOC-2 resolved |
| ARCH-3 | P2 | CLOSED | `eval/runner.py:184` calls `check_budget()` before LLM — FIX-E resolved |
| ARCH-4 | P2 | CLOSED | `rca_clusterer.py` now has `rca.run`, `rca.cluster`, `rca.summarize` spans — FIX-D resolved |
| ARCH-5 | P2 | CLOSED | ARCHITECTURE.md v3.0 documents `/metrics` exemption — DOC-1 resolved |
| ARCH-6 | P2 | OPEN | Cluster detail uses timestamp heuristic, not persisted membership (`app/routers/clusters.py:151-175`) |
| ARCH-7 | P2 | CLOSED | `app/agent.py` has zero fastapi imports — domain exceptions in `app/exceptions.py`, SVC-3 resolved |
| ARCH-8 | P2 | CLOSED | Router business logic extracted to AuthService + EvalService — SVC-1/SVC-2 resolved |
| P2-1 | P2 | CLOSED | Redis keys tenant-namespaced — FIX-A resolved (superseded by CODE-14 prefix-order note) |
| P2-9 | P2 | CLOSED | `_run_blocking()` extracted to `app/utils.py` — FIX-B resolved |
| P2-10 | P2 | OPEN | Module-level settings access requires API key at import time (`app/main.py:223`) |
| ARCH-9 | P2 | CLOSED | `GET /eval/runs` implemented in `app/routers/eval.py` and covered by tests |
| REG-1 | P1 | CLOSED | Cycle 8 regressions resolved; full test suite green |

─── T13 ✅ · EmbeddingService — DONE ────────────────────────────────

Files created: app/embedding_service.py, tests/test_embedding_service.py
Files modified: app/agent.py, app/config.py

─── T14 ✅ · RCA Clusterer Background Job — DONE ────────────────────

Files created: app/jobs/__init__.py, app/jobs/rca_clusterer.py, tests/test_rca_clusterer.py
Files modified: app/main.py, app/config.py

✅ FIX-6 and FIX-7 verified resolved (Cycle 5, 2026-03-08).

─── T15 ✅ · Cluster API Endpoints — DONE ───────────────────────────

Files created: app/routers/clusters.py
Files modified: app/main.py, tests/test_endpoints.py

─── NEXT ─────────────────────────────────────────────────────────────

Core roadmap is complete through T24.
Recommended next work: close remaining review findings, reduce architecture drift,
and package the system for external demos or pilot customers.

─── Implementation decisions Codex MUST NOT change ──────────────────

Full contract: docs/IMPLEMENTATION_CONTRACT.md (read once per session).
Summary of immutable rules (A–I):

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

4. READ the sections of docs/spec.md and docs/ARCHITECTURE.md relevant to the task.

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

docs/IMPLEMENTATION_CONTRACT.md — Immutable rules A–I + security + forbidden actions
docs/spec.md           — Product scope, SLAs, security assumptions, API surface
docs/ARCHITECTURE.md   — Component diagram, data flow, failure handling
docs/data-map.md       — All entities, schemas, Redis keys, RLS policies, PII rules
docs/tasks.md          — Task graph; your work queue
docs/dev-standards.md  — Code style, test strategy, commit discipline, observability hooks
docs/observability.md  — Metric names, span hierarchy, alerting strategy
docs/agent-registry.md — All agents, pipeline design, LLM tools, guardrails, failure modes
docs/llm-usage.md      — Prompt versioning rules, error categories, hallucination tracking
docs/load-profile.md   — Load scenarios and KPIs
docs/adr/              — Architectural decisions; read before making structural choices
docs/audit/REVIEW_REPORT.md — Current open findings (P0/P1/P2)

If a task conflicts with any governing document, STOP and report the conflict.
Do not resolve conflicts silently. Architecture decides; Codex implements.

── DEVELOPMENT LOOP ─────────────────────────────────────────────────

Automated: paste docs/prompts/ORCHESTRATOR.md to Claude Code.
Manual: see docs/DEVELOPMENT_METHOD.md and docs/audit/review_pipeline.md.
