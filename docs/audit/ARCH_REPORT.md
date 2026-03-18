---
# ARCH_REPORT — Cycle 9
_Date: 2026-03-18_

## Component Verdicts

| Component | Verdict | Note |
|-----------|---------|------|
| `app/agent.py` — AgentService | VIOLATION | Imports `HTTPException` from FastAPI (ARCH-7); service layer must not depend on transport layer |
| `app/main.py` — FastAPI entrypoint | PASS | Lifespan, middleware stack, core endpoints correct; `/metrics` exemption comment-documented |
| `app/llm_client.py` — LLMClient | PASS | Tool-use loop ≤5 turns; `summarize_cluster_async` uses `asyncio.to_thread` (CODE-9 resolved) |
| `app/dedup.py` — DedupCache | PASS | Key format `dedup:{tenant_id}:{message_id}` matches data-map §3; CODE-11 resolved |
| `app/approval_store.py` — RedisApprovalStore | PASS | Key format `pending:{tenant_id}:{pending_id}` matches data-map §3; CODE-11 resolved |
| `app/middleware/rate_limit.py` — RateLimitMiddleware | PASS | Key format `ratelimit:{tenant}:{user_id}`; anonymous fallback for pre-auth webhook; CODE-11 resolved |
| `app/middleware/auth.py` — JWTMiddleware | DRIFT | `/metrics` exemption present but policy contract not in ARCHITECTURE.md or any ADR (ARCH-5 open) |
| `app/routers/auth.py` — auth router | VIOLATION | bcrypt + JWT minting directly in route handler; no service layer (ARCH-8); business logic in transport layer |
| `app/routers/eval.py` — eval router | VIOLATION | Direct DB INSERT for eval_run record in route handler; no service layer (ARCH-8) |
| `app/routers/clusters.py` — clusters router | DRIFT | `GET /clusters/{cluster_id}` returns ticket_ids via time-window heuristic on `ticket_embeddings`, not persisted membership (ARCH-6) |
| `app/jobs/rca_clusterer.py` — RCAClusterer | PASS | `rca.run`, `rca.cluster`, `rca.summarize` OTel spans present; async summarize via `asyncio.to_thread`; ARCH-4 resolved |
| `eval/runner.py` — EvalRunner | PASS | `check_budget()` called before each LLM case iteration at line 184; ARCH-3 resolved |
| `app/cost_ledger.py` — CostLedger | PASS | check_budget + record implemented |
| `app/embedding_service.py` — EmbeddingService | PASS | Voyage AI / voyage-3-lite / 1024 dims; matches data-map §2 |
| `app/dependencies.py` — require_role | PASS | Role enforcement via FastAPI Depends; correct layer |

---

## ADR Compliance

| ADR | Verdict | Note |
|-----|---------|------|
| ADR-001 Storage: PostgreSQL + RLS + Redis cache | PASS | Postgres primary store, RLS enforced via `SET LOCAL app.current_tenant_id`, Redis TTL cache for tenant config |
| ADR-002 Vector DB: pgvector conditional | DRIFT | ADR specifies `text-embedding-3-small` (OpenAI) / VECTOR(1536); implementation uses `voyage-3-lite` / VECTOR(1024). ADR text not updated since provider change. |
| ADR-003 RBAC: HS256 JWT | PASS | ADR-003 §JWT Structure explicitly specifies HS256; implementation matches. P1-1 was a misattribution — the RS256 reference exists only in ARCHITECTURE.md prose, not in ADR-003. Revisit for v2 OAuth migration. |
| ADR-004 Observability: OTel spans per pipeline stage | PASS | `rca_clusterer.py` now has `rca.run` / `rca.cluster` / `rca.summarize` spans; ARCH-4 resolved. `/metrics` exemption policy still lacks formal documentation (ARCH-5). |
| ADR-005 Orchestration: Claude tool_use loop ≤5 turns | PASS | `llm_client.py` enforces `max_turns=5`; APScheduler in `main.py` lifespan matches §v1 Implementation contract |

---

## Architecture Findings

### ARCH-2 [P2] — ADR-002 embedding model spec drift
Symptom: ADR-002 specifies `text-embedding-3-small` (OpenAI) and `VECTOR(1536)`; runtime config and schema use `voyage-3-lite` and `VECTOR(1024)`.
Evidence: `docs/adr/002-vector-database.md:32` (`VECTOR(1536)`), `app/config.py:29` (`embedding_model: str = "voyage-3-lite"`), `docs/data-map.md:116` (`VECTOR(1024)`).
Root cause: ADR-002 was authored before the embedding provider was finalized; never updated when Voyage AI was adopted.
Impact: ADR is misleading; HNSW tuning parameters in ADR-002 are sized for 1536-dim vectors — incorrect for the running system.
Fix: Update ADR-002 to reflect `voyage-3-lite` / 1024 dims; revise HNSW parameters; add "Updated 2026-03-18" to status. Tracked as DOC-2.

### ARCH-5 [P2] — `/metrics` auth contract undocumented at architecture level
Symptom: `GET /metrics` is exempt from JWT auth; the exemption is justified in a code comment but is absent from ARCHITECTURE.md, any ADR, and any ops runbook.
Evidence: `app/middleware/auth.py:57` (exemption with comment), `app/main.py:368-371` (route), `docs/ARCHITECTURE.md` (no `/metrics` auth section).
Root cause: FIX-F documentation deferred; policy is implicit in code only.
Impact: Any engineer reading ARCHITECTURE.md cannot determine the intended auth model. Per-tenant Prometheus labels (e.g. `tenant_id_hash`) are readable by any network-reachable client.
Fix: Add an explicit §Security Assumptions entry to ARCHITECTURE.md: "`GET /metrics` is exempt from application-level JWT auth; access restriction is enforced at the network/infrastructure layer (VPC firewall, Prometheus scrape IP allowlist). No per-tenant RBAC is enforced at the application layer." Tracked as FIX-F.

### ARCH-6 [P2] — Cluster membership is a time-window approximation
Symptom: `GET /clusters/{cluster_id}` returns tickets by querying `ticket_embeddings` where `created_at BETWEEN cluster.first_seen AND cluster.last_seen`, not via persisted cluster membership.
Evidence: `app/routers/clusters.py:151-175`.
Root cause: No `cluster_memberships` join table exists; `cluster_summaries` stores only aggregate time bounds. Any ticket in the time window appears regardless of DBSCAN cluster assignment.
Impact: Endpoint is non-deterministic — overlapping time windows across clusters produce incorrect ticket attribution. Violates spec §7 `ClusterSummary` entity contract.
Fix: Add `cluster_memberships(cluster_id UUID, ticket_id UUID)` table; populate in `_upsert_cluster` (`app/jobs/rca_clusterer.py`); join on membership in the clusters router. Requires Alembic migration.

### ARCH-7 [P2] — AgentService imports HTTPException from FastAPI
Symptom: `app/agent.py:15` imports `HTTPException` from `fastapi`; the service layer must not depend on the transport/framework layer.
Evidence: `app/agent.py:15` (`from fastapi import HTTPException`).
Root cause: HTTPException was used as a convenience exception during initial development and never extracted.
Impact: `app/agent.py` is coupled to FastAPI; cannot be reused or unit-tested without the FastAPI dependency. Blocks SVC-1 service extraction in Phase 9.
Fix: Define `class AgentError(Exception)` in `app/exceptions.py`; replace `HTTPException` usage in `agent.py` with domain exceptions; catch in `main.py` route handlers and map to HTTP status codes.

### ARCH-8 [P2] — Router layer carries business logic
Symptom: `app/routers/auth.py` performs bcrypt hash verification and JWT minting directly in the route handler (lines 26–96). `app/routers/eval.py` performs direct DB INSERT for `eval_runs` in the route handler (lines 77–95).
Evidence: `app/routers/auth.py:26-96`, `app/routers/eval.py:77-95`.
Root cause: Service layer for auth and eval was never extracted; logic grew inline in route handlers.
Impact: Business logic is untestable without FastAPI `Request` context. Blocks Phase 9 SVC-1 (AuthService) and SVC-2 (EvalService) extraction.
Fix: Extract `AuthService.authenticate(email, password, tenant_slug)` → `app/services/auth_service.py`; extract `EvalService.start_run(tenant_id)` → `app/services/eval_service.py`; route handlers become thin coordinators. Deferred to Phase 9.

---

## Resolved Since Cycle 8

| Finding | Resolution |
|---------|------------|
| ARCH-3 (eval budget bypass) | `eval/runner.py:184` calls `check_budget()` before each LLM case — CLOSED |
| ARCH-4 (RCA OTel gap) | `rca_clusterer.py` now has `rca.run`, `rca.cluster`, `rca.summarize` spans — CLOSED |
| CODE-9 (blocking sync in async RCA path) | `summarize_cluster_async` uses `asyncio.to_thread` — CLOSED |
| CODE-11 (Redis keys not tenant-namespaced) | All three hot-path keys now tenant-prefixed per data-map §3 — CLOSED |
| ARCH-9 (`GET /eval/runs` missing) | Implemented in `app/routers/eval.py` — CLOSED (Cycle 8) |

---

## Doc Patches Needed

| File | Section | Change |
|------|---------|--------|
| `docs/adr/002-vector-database.md` | Decision (line 32) | Replace `VECTOR(1536)` / `text-embedding-3-small` with `VECTOR(1024)` / `voyage-3-lite`; update HNSW size estimates; add "Updated 2026-03-18" |
| `docs/ARCHITECTURE.md` | §2.1 Component Status | Add T05–T24 components: `app/routers/auth.py`, `app/routers/eval.py`, `app/routers/clusters.py`, `app/routers/tickets.py`, `app/routers/agents.py`, `app/routers/analytics.py`, `app/jobs/rca_clusterer.py`, `app/embedding_service.py`, `app/cost_ledger.py`, `app/metrics.py`, `app/dependencies.py`, `app/utils.py` |
| `docs/ARCHITECTURE.md` | §2.2 Repository Layout | Add `app/routers/`, `app/jobs/`, `app/services/` subtrees |
| `docs/ARCHITECTURE.md` | §5 Security Assumptions | Add `/metrics` auth contract: "exempt from JWT; restricted at network layer" |
| `docs/ARCHITECTURE.md` | Header | Bump to v2.2, date 2026-03-18 |
---
