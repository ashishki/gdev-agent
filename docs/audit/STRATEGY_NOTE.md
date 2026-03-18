# STRATEGY_NOTE — Phase 9
_Date: 2026-03-18_

---

## Platform Identity

Phase 9 tasks (FIX-G, SVC-1, SVC-2, SVC-3, DOC-1, DOC-2, DOC-3) are entirely structural: Redis key inversion, service layer extraction, and documentation alignment. Every task directly resolves a named finding (CODE-14, ARCH-7, ARCH-8, ARCH-2, ARCH-5) that accumulated through the triage pipeline's growth. Service layer extraction in particular positions `agent.py` and the routers as clean single-responsibility components — a prerequisite for onboarding the system to pilot customers without risking regressions from cross-layer coupling. There is no feature dilution; Phase 9 strengthens platform identity by making the "AI Support Intelligence" pipeline structurally sound and documentable at v3.0.

---

## Structural Drift Assessment

| Finding | Cycles open | Structural pattern | Action |
|---|---|---|---|
| CODE-14 — Redis key prefix order deviates from data-map §3 | 1 (Phase 8 tracking, Phase 9 fix) | Data isolation: `dedup:{tenant_id}:` instead of `{tenant_id}:dedup:` prevents per-tenant Redis ACL grants; blocks clean tenant eviction | Must resolve — FIX-G scheduled first |
| CODE-15 — `auth_ratelimit` key has no tenant prefix | 1 | Intentional global design but absent from data-map §3; creates a documentation and operational gap | Carry forward — global pre-auth path is by design; DOC-1 should note this in the Redis key table |
| ARCH-7 — `app/agent.py` imports `HTTPException` from FastAPI | 3+ | Layer violation: service layer coupled to web framework; prevents agent reuse outside FastAPI (CLI, tests without HTTP context) | Must resolve — SVC-3 scheduled |
| ARCH-8 — Business logic in `app/routers/auth.py` and `app/routers/eval.py` | 3+ | Layer violation: routers carry token creation, blocklist management, and eval orchestration; fat router pattern blocks unit testing without HTTP context | Must resolve — SVC-1 and SVC-2 scheduled |
| ARCH-2 — ADR-002 documents OpenAI/1536-dim; live code uses Voyage/1024-dim | 2+ | ADR drift: schema was written for `VECTOR(1536)` but `EmbeddingService` emits 1024-dim vectors; if the Alembic migration created the column at 1536 dims, ANN queries silently fail or reject inserts | Must resolve — DOC-2 scheduled; **Codex must verify Alembic migration column dimension before implementing DOC-2** |
| CODE-5 — Broad `except Exception` in `_fetch_embeddings` swallowed silently | 3+ | Silent failure masking: forbidden by IMPLEMENTATION_CONTRACT; no `LOGGER.warning`; not in Phase 9 task list | Carry forward — add explicit task in Phase 10 backlog |
| CODE-10 — `run_blocking` raises untyped `data` (`type: ignore`) | 2+ | Type safety gap: `raise data` on non-Exception bypasses static analysis; low blast radius but accumulates mypy suppression debt | Carry forward — add to Phase 10 cleanup backlog |
| CODE-12 / P2-10 — Module-level `get_settings()` at import time in `app/main.py` | 2+ | Startup coupling: requires `ANTHROPIC_API_KEY` in environment at import; breaks test isolation without env patching | Carry forward — acceptable for Phase 9; schedule for Phase 10 or CLI-1 (CLI needs clean import) |
| CODE-13 — `run_eval()` non-async path has no `check_budget()` | 1 | Safety gate bypass: CLI path skips budget enforcement; SVC-2 extraction must include budget check in `EvalService.create_run()` | Must resolve within SVC-2 — acceptance criteria must explicitly cover budget check |
| ARCH-6 — Cluster detail uses timestamp heuristic, not persisted membership | 2+ | Data integrity: `app/routers/clusters.py` reconstructs cluster membership from timestamps rather than a persisted join table; inaccurate results under high ticket volume | Carry forward — CLU-1/CLU-2 scheduled in Phase 10 |

**Structural verdict:** ARCH-7 and ARCH-8 have been open for 3+ cycles and are the heart of Phase 9. They must both close this phase. ARCH-2 (embedding dimension mismatch) is a data integrity risk that DOC-2 targets but only partially: the ADR update is necessary but the Alembic migration column dimension (`VECTOR(1536)` vs `VECTOR(1024)`) must be audited and corrected if mismatched — a schema migration may be required.

---

## ADR Alignment

| ADR | Conflict | Recommendation |
|---|---|---|
| ADR-002 (pgvector / embedding model) | ADR-002 specifies `VECTOR(1536)` with OpenAI `text-embedding-3-small`. `EmbeddingService` uses Voyage AI and emits 1024-dim vectors. DOC-2 updates the ADR text, but the underlying Alembic migration `ticket_embeddings.embedding` column may still be `VECTOR(1536)`. If so, inserts silently fail or Postgres rejects the vector dimension mismatch. | Update ADR (DOC-2). Additionally: inspect `alembic/versions/` for the `ticket_embeddings` column definition. If dimension is 1536, a new migration to `VECTOR(1024)` is required before DOC-2 can be marked done. Do not mark DOC-2 complete on documentation alone if schema is still 1536. |
| ADR-003 (RBAC / JWT) | FIX-G changes the Redis key prefix for `ratelimit:{tenant_id}:{user_id}`. The anonymous/webhook fallback becomes `anonymous:ratelimit:{user_id}`. ADR-003 §Enforcement describes per-tenant rate limiting; the new key format aligns better with the ADR's tenant isolation intent. No conflict — the ADR does not specify key format; the implementation becomes more ADR-consistent. | No ADR update needed. |
| ADR-004 (OTel + Prometheus) | SVC-1 and SVC-2 create new service classes. ADR-004 and the IMPLEMENTATION_CONTRACT both mandate OTel span + Prometheus counter per service method. The task specs for SVC-1 and SVC-2 include this explicitly. No conflict if the requirement is met. | No ADR update needed. Codex must not skip observability hooks when implementing service methods. |
| ADR-005 (APScheduler / async jobs) | SVC-2 extracts `EvalService` from `app/routers/eval.py`. The eval runner (`eval/runner.py`) is an async job called on-demand; ADR-005 designates it as "on-demand via POST /eval/run; no scheduler entry." SVC-2 formalizes this design without changing the invocation model. No conflict. | No ADR update needed. |

---

## Phase Risk

**Highest-risk task: SVC-3 — Fix agent.py HTTP boundary violation**

Risk factors:
1. `app/agent.py` raises `HTTPException` in multiple call paths. Introducing `AgentError`, `BudgetError`, and `ValidationError` domain exceptions requires tracing every `raise HTTPException(...)` in `agent.py` and every caller that catches `HTTPException` explicitly. A missed catch site will silently pass an uncaught domain exception up to the ASGI server, returning HTTP 500 instead of the intended status code.
2. `app/main.py` exception handlers must map each domain exception to the correct HTTP status code. If the handler registration order is wrong (more specific after more general), some domain exceptions will be handled by the wrong handler.
3. `tests/test_agent.py` likely imports `HTTPException` expectations directly. Updating these tests requires care to avoid masking real behavior changes — the test must verify the HTTP status code via `TestClient`, not by catching `HTTPException` in unit scope.

**Required test:** `tests/test_agent.py` must include a test that invokes the agent pipeline with a condition that triggers each domain exception (`AgentError`, `BudgetError`, `ValidationError`) and asserts the correct HTTP status code is returned via `TestClient` — not by catching the exception directly. A missing-budget case (`BudgetError` → HTTP 402 or 429) and an invalid-input case (`ValidationError` → HTTP 422) are the minimum coverage required.

**Secondary risk: DOC-2 — ADR-002 vector stack alignment**

DOC-2 is classified as doc-only but may conceal a latent schema bug. If `alembic/versions/` contains `VECTOR(1536)` for `ticket_embeddings.embedding`, the system has been inserting 1024-dim vectors into a 1536-dim column since T13. Postgres pgvector rejects dimension mismatches with an error, which means either: (a) the column was never actually created as VECTOR(1536) and the test suite uses SQLite fallback without pgvector, masking the mismatch; or (b) embeddings are silently not being stored. This must be verified before DOC-2 is marked complete.

---

## Recommendation

**Proceed with modification.**

Execute Phase 9 tasks in the following order:

1. **FIX-G first** — lowest risk, highest operational value (enables per-tenant Redis ACL); all three hot-path files must be updated atomically in a single commit.
2. **SVC-1** — extract `AuthService`; depends on T05/T06/T06B which are complete; creates the `app/services/` package for SVC-2.
3. **SVC-2** — extract `EvalService`; depends on SVC-1 having established the package. **Modification required:** acceptance criteria for SVC-2 must explicitly include a `check_budget()` call inside `EvalService.create_run()` to close CODE-13. This is not stated in the current task spec and must be added before implementation begins.
4. **SVC-3** — highest-risk task; implement after SVC-1 and SVC-2 are green so the test suite is stable before the exception boundary changes.
5. **DOC-2** — before writing, inspect `alembic/versions/` for the `ticket_embeddings` embedding column dimension. If it is `VECTOR(1536)`, create a new Alembic migration to `VECTOR(1024)` and include it in DOC-2's scope. Do not mark DOC-2 done on documentation alone.
6. **DOC-1** — depends on SVC-1/SVC-2/SVC-3 complete; update ARCHITECTURE.md to v3.0 reflecting new `app/services/` layer, corrected Redis key namespace, and Voyage/1024-dim embedding stack.
7. **DOC-3** — independent; can run in parallel with DOC-1.

**Modification required before start:** Add `check_budget()` call to SVC-2 acceptance criterion #1 in `docs/tasks.md` to close CODE-13. Without this, the eval budget bypass (3+ cycles open) will survive another full phase.
