---
# ARCH_REPORT — Cycle 8
_Date: 2026-03-09_

## Component Verdicts

| Component | Verdict | Note |
|-----------|---------|------|
| `app/agent.py` (AgentService) | VIOLATION | Imports `HTTPException` from FastAPI (transport type) at line 15 — ARCH-7 |
| `app/routers/auth.py` | DRIFT | Route handler contains full business logic: bcrypt comparison, JWT construction, credential lookup — ARCH-8 |
| `app/routers/eval.py` (POST /eval/run) | DRIFT | Route handler performs direct DB INSERT; `GET /eval/runs` entirely absent — ARCH-9 |
| `app/routers/clusters.py` (cluster detail) | DRIFT | Returns tickets via time-window heuristic on `ticket_embeddings`, not persisted cluster membership — ARCH-6 |
| `app/main.py` (/webhook) | PASS | Business logic fully delegated to `AgentService` |
| `app/main.py` (/approve) | PASS | Delegates to `AgentService.approve()` |
| `app/main.py` (/metrics) | DRIFT | Exempt from JWT auth; no RBAC; violates spec §5 security assumption — ARCH-5 |
| `app/middleware/auth.py` | PASS | HS256 JWT, blocklist, fail-closed; exemption list explicit |
| `app/middleware/rate_limit.py` | DRIFT | Redis keys not tenant-namespaced (`ratelimit:{user}` vs spec `{tenant_id}:{user}`) — CODE-11 |
| `app/dedup.py` | DRIFT | Redis key `dedup:{message_id}` missing `{tenant_id}:` prefix — CODE-11 |
| `app/approval_store.py` | DRIFT | Redis key `pending:{id}` missing `{tenant_id}:` prefix — CODE-11 |
| `app/jobs/rca_clusterer.py` | DRIFT | Zero OTel span instrumentation; no trace/span imports found — ARCH-4 |
| `eval/runner.py` | DRIFT | `CostLedger.record()` called ✅; `CostLedger.check_budget()` absent before LLM call — ARCH-3 |
| `load_tests/` (T23) | PASS | No app-layer architectural concern; correct isolation as test harness |
| `docker-compose.yml` (T24) | PASS | Full observability stack (Prometheus, Grafana, Loki, Tempo) consistent with ADR-004 |

---

## ADR Compliance

| ADR | Verdict | Note |
|-----|---------|------|
| ADR-001 Storage: PostgreSQL + RLS + Redis | DRIFT | Postgres + RLS implemented ✅; Redis key namespacing violates isolation model (CODE-11) |
| ADR-002 Vector DB: pgvector conditional | VIOLATION | ADR specifies `VECTOR(1536)` + OpenAI `text-embedding-3-small`; runtime uses `VECTOR(1024)` + Voyage AI `voyage-3-lite`; ADR not updated — ARCH-2 |
| ADR-003 RBAC: HS256 | PASS | ADR-003 body explicitly mandates HS256 for v1; implementation matches; ARCH-1 closed in Cycle 7 |
| ADR-004 Observability: OTel + Prometheus | DRIFT | Prometheus metrics + Docker stack ✅; RCA Clusterer has zero OTel span instrumentation — ARCH-4 |
| ADR-005 Orchestration: Claude tool_use ≤5 turns | PASS | APScheduler in use; eval uses `asyncio.create_task` (on-demand, acceptable per ADR-005); tool_use ≤5 turns confirmed |

---

## Architecture Findings

### ARCH-2 [P2] — ADR-002 vector stack drift: docs say OpenAI/1536, runtime uses Voyage/1024
Symptom: ADR-002 specifies `VECTOR(1536)` + `text-embedding-3-small` (OpenAI). Runtime config and data-map use `VECTOR(1024)` + `voyage-3-lite` (Voyage AI).
Evidence: `docs/adr/002-vector-database.md:32` vs `app/config.py:29` + `docs/data-map.md:116`
Root cause: ADR written before embedding model was changed; data-map.md was updated but ADR was not.
Impact: ADR is the authoritative architectural record; drift misleads reviewers and future engineers about the vector stack.
Fix: Update `docs/adr/002-vector-database.md` — change decision section to `VECTOR(1024)`, model to `voyage-3-lite` (Voyage AI), add amendment note with date.

### ARCH-3 [P2] — Eval LLM cost path bypasses CostLedger budget check
Symptom: `eval/runner.py` calls `CostLedger.record()` (post-call accounting) but does not call `CostLedger.check_budget()` before invoking the LLM.
Evidence: `eval/runner.py:199` (record ✅); no `check_budget` call anywhere in `eval/runner.py` or `app/routers/eval.py`
Root cause: Eval path added without integrating the pre-call budget guard.
Impact: Eval runs can exhaust tenant budgets unchecked; violates spec §5 rule #6 ("quotas enforced before the API call is made").
Fix: Call `CostLedger(db_session).check_budget(tenant_id)` at the start of `run_eval_job` before the first LLM invocation; raise `BudgetExhaustedError` if over limit.

### ARCH-4 [P2] — RCA OTel background span hierarchy incomplete
Symptom: `app/jobs/rca_clusterer.py` has zero OpenTelemetry imports or span instrumentation.
Evidence: grep for `trace|span|tracer|opentelemetry` in `app/jobs/rca_clusterer.py` returns no matches.
Root cause: OTel instrumentation was not added when the RCA job was implemented.
Impact: ADR-004 mandates spans per pipeline stage including background jobs (`agent.embed` linked trace per spec). RCA runs are invisible in distributed tracing; latency breakdown and error correlation are impossible.
Fix: Add `tracer = trace.get_tracer(__name__)`; wrap `run_for_tenant`, `_fetch_embeddings`, `_upsert_cluster`, and summarize calls in named spans with `tenant_id_hash` attribute.

### ARCH-5 [P2] — /metrics exposure/auth contract not reconciled with spec security assumptions
Symptom: `GET /metrics` is exempt from JWT auth (hardcoded in `JWTMiddleware`) and has no RBAC dependency in the route.
Evidence: `app/main.py:364-366` (no auth); `app/middleware/auth.py:55` (`GET /metrics` in exemption list)
Root cause: Prometheus scrape requirement conflicts with JWT auth; exemption added without reconciling spec security assumptions.
Impact: Prometheus metrics (including `gdev_llm_cost_usd_total{tenant}`, `gdev_pending_total{tenant}`) are publicly readable; violates spec §5 assumption #2 and leaks per-tenant operational data.
Fix: Record an explicit architectural decision: (a) restrict scrape to internal network only (infra enforced, no code change) or (b) add Bearer token auth to scrape job and remove exemption. Either choice must be captured in an ADR amendment or new ADR.

### ARCH-6 [P2] — Cluster detail endpoint uses time-window heuristic, not persisted membership
Symptom: `GET /clusters/{cluster_id}` returns ticket IDs by querying `ticket_embeddings` within `first_seen`/`last_seen` window, not from a persisted cluster membership table.
Evidence: `app/routers/clusters.py:151-175`
Root cause: No `cluster_memberships` join table exists; `cluster_summaries` has no ticket-to-cluster link.
Impact: Cluster detail is approximate; tickets that arrived in the time window but are not semantic members of the cluster are returned, misleading operators during incident triage.
Fix: Add `cluster_ticket_memberships(cluster_id, ticket_id, tenant_id)` table populated by the RCA clusterer. Update `GET /clusters/{cluster_id}` to query this table instead of the time window.

### ARCH-7 [P2] — agent.py imports HTTPException (service/transport boundary violation)
Symptom: `app/agent.py` imports `HTTPException` from FastAPI at module level.
Evidence: `app/agent.py:15` — `from fastapi import HTTPException`
Root cause: HTTPException used directly in the service layer instead of defining domain exceptions.
Impact: Service layer has a hard dependency on the FastAPI transport layer, preventing reuse in non-HTTP contexts (CLI, background jobs, tests) and violating layered architecture.
Fix: Define `class AgentError(Exception)` and subclasses in `app/exceptions.py`; raise domain exceptions in `app/agent.py`; catch and convert to `HTTPException` in route handlers only.

### ARCH-8 [P2] — Router layer carries business logic
Symptom: `app/routers/auth.py` performs credential lookup, bcrypt comparison, and JWT construction inline. `app/routers/eval.py` performs direct DB INSERT for eval_run record creation in the route handler.
Evidence: `app/routers/auth.py:26-96`; `app/routers/eval.py:77-95`
Root cause: No `AuthService` or `EvalService` exists; logic written directly in route handlers.
Impact: Business logic is untestable without HTTP context; violates layered architecture.
Fix: Extract credential verification + JWT issuance to `app/services/auth_service.py`; extract eval run creation to `app/services/eval_service.py`. Route handlers call service methods only.

### ARCH-9 [P2] — GET /eval/runs endpoint missing (AC-2 open)
Symptom: spec §8 mandates `GET /eval/runs` (JWT auth, list eval run history). Only `POST /eval/run` exists.
Evidence: `app/routers/eval.py` — no `@router.get` decorator present; spec §8 API surface table row unimplemented.
Root cause: T22 is in-progress; AC-2 was not completed before Cycle 8 snapshot.
Impact: API surface gap; eval run history is unqueryable by clients; spec contract not fulfilled.
Fix: Implement `GET /eval/runs` with cursor pagination, `require_role("tenant_admin", "support_agent")`, response mapped from `eval_runs` table.

---

## Doc Patches Needed

| File | Section | Change |
|------|---------|--------|
| `docs/adr/002-vector-database.md` | Decision | Change `VECTOR(1536)` → `VECTOR(1024)`; model from `text-embedding-3-small` (OpenAI) → `voyage-3-lite` (Voyage AI); add amendment note dated 2026-03-09 |
| `docs/ARCHITECTURE.md` | §2.1 Component Status | Add eval subsystem row: `app/routers/eval.py` + `eval/runner.py` — status `In Progress (T22)`; note AC-2 open |
| `docs/ARCHITECTURE.md` | §2.1 Component Status | Add load test harness row: `load_tests/` — status `Done (T23)` |
| `docs/ARCHITECTURE.md` | §2.1 Component Status | Update docker-compose row to reflect T24 additions (pgvector, Prometheus, Grafana, Loki, Tempo) |
| `docs/spec.md` | §5 Security Assumptions | Clarify `/metrics` exposure model (internal-only scrape or authenticated scrape) to reconcile with ARCH-5 |

---
