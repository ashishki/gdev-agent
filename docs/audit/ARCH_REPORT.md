---
# ARCH_REPORT — Cycle 7
_Date: 2026-03-08_

## Component Verdicts
| Component | Verdict | Note |
|-----------|---------|------|
| `app/agent.py` | VIOLATION | Service-layer boundary breach remains: service imports/raises FastAPI `HTTPException`, coupling domain logic to transport. |
| `app/main.py` | DRIFT | Route handlers still own orchestration logic (dedup, tenant resolution, error mapping); `/metrics` is publicly exposed and JWT-exempt without spec-level contract alignment. |
| `app/middleware/auth.py` | DRIFT | JWT middleware works, but `/metrics` and `/webhook` are auth-exempt while spec states all API calls require JWT and `/webhook` uses `HMAC + JWT`. |
| `app/routers/auth.py` | VIOLATION | Auth route contains substantial business logic (credential validation, DB tenancy setup, JWT issuance) instead of a service boundary. |
| `app/routers/clusters.py` | VIOLATION | Cluster-detail route returns ticket IDs via time-window heuristic, not persisted cluster membership semantics. |
| `app/jobs/rca_clusterer.py` | DRIFT | RCA has Prometheus metrics, but no OTel span hierarchy and no CostLedger budget/accounting path for RCA summarization calls. |
| `app/config.py` | DRIFT | Runtime remains `HS256`; carry-forward architecture gate (P1-1) still flags RS256+JWKS as unresolved. |
| `app/embedding_service.py` | DRIFT | Embedding stack is Voyage + 1024 dimensions, while ADR-002 text still specifies OpenAI + 1536. |

## ADR Compliance
| ADR | Verdict | Note |
|-----|---------|------|
| ADR-001 Storage: PostgreSQL + RLS + Redis cache | DRIFT | Postgres+RLS are active, but hot Redis keys (`dedup`, `pending`, `ratelimit`) are not tenant-prefixed as required by current architecture contracts. |
| ADR-002 Vector DB: pgvector conditional | DRIFT | Runtime/data-map are Voyage/1024; ADR still documents OpenAI/1536 and associated sizing assumptions. |
| ADR-003 RBAC: **P1-1 open** — RS256 mandated, HS256 implemented. Still open? | VIOLATION | Still open for this review gate: implementation is HS256 with no JWKS endpoint. |
| ADR-004 Observability: OTel spans + Prometheus in new services? | DRIFT | Prometheus coverage exists, but RCA background flow lacks explicit OTel spans/tracing topology. |
| ADR-005 Orchestration: Claude tool_use loop ≤5 turns | DRIFT | `tool_use` loop cap is compliant (`max_turns=5`), but RCA timeout is 300s vs ADR example 120s without ADR/spec rationale. |

## Architecture Findings
### ARCH-1 [P1] — RBAC Crypto Contract Still Unresolved
Symptom: Runtime continues HS256 JWT signing/verification and no JWKS endpoint.
Evidence: `app/config.py:49`, `app/routers/auth.py:94`, `app/middleware/auth.py:75`, `docs/audit/META_ANALYSIS.md:10`
Root cause: Carry-forward architecture decision (P1-1) was not closed with either RS256 implementation or an explicit accepted ADR amendment.
Impact: Security architecture gate remains open on an auth-critical path.
Fix: Close the decision explicitly: implement RS256+JWKS, or formally amend architecture gates/ADR stack to HS256 and remove RS256 requirement.

### ARCH-2 [P2] — Vector Architecture Drift (ADR vs Runtime)
Symptom: ADR-002 specifies OpenAI 1536-d vectors, but runtime and data map are Voyage 1024-d.
Evidence: `docs/adr/002-vector-database.md:32`, `docs/adr/002-vector-database.md:36`, `docs/data-map.md:115`, `app/config.py:29`, `app/embedding_service.py:86`
Root cause: Embedding-model migration landed in code/docs-data-map without ADR update.
Impact: Capacity/performance assumptions in architecture records are stale.
Fix: Update ADR-002 to Voyage/1024 (or revert runtime/schema to ADR target).

### ARCH-3 [P2] — RCA Cost Path Bypasses CostLedger Guard/Accounting
Symptom: RCA summarization path invokes LLM directly with no per-tenant budget check or cost ledger write.
Evidence: `app/jobs/rca_clusterer.py:297`, `app/llm_client.py:274`, `app/agent.py:151`, `app/agent.py:706`
Root cause: Cost controls were implemented in webhook agent flow but not extended to RCA background jobs.
Impact: RCA can consume unbudgeted LLM spend and weaken tenant budget guarantees.
Fix: Add CostLedger check/record around RCA summarization calls (or an RCA budget policy explicitly documented in spec/ADR).

### ARCH-4 [P2] — RCA Observability Topology Incomplete
Symptom: RCA exposes Prometheus metrics but has no OpenTelemetry spans around tenant runs/cluster upserts.
Evidence: `app/jobs/rca_clusterer.py:27`, `app/jobs/rca_clusterer.py:177`, `app/jobs/rca_clusterer.py:191`, `docs/adr/004-observability-stack.md:58`
Root cause: Metrics instrumentation shipped without parallel trace instrumentation in background job path.
Impact: RCA failures/latency cannot be traced end-to-end in the declared OTel architecture.
Fix: Add tracer spans for `run_for_all_tenants`, `run_tenant`, and `_upsert_cluster` with tenant-safe attributes.

### ARCH-5 [P2] — Metrics/Auth Exposure Contract Drift
Symptom: `/metrics` is publicly exposed and JWT-exempt, while spec defines JWT-protected metric APIs and “all API calls require JWT”.
Evidence: `app/main.py:362`, `app/middleware/auth.py:54`, `docs/spec.md:91`, `docs/spec.md:194`
Root cause: Runtime observability endpoint contract evolved without spec reconciliation.
Impact: Security posture for operational telemetry is ambiguous and potentially overexposed.
Fix: Either protect `/metrics` (or isolate network-level access), and align spec/API contract accordingly.

### ARCH-6 [P2] — Cluster Membership Contract Not Implemented
Symptom: `GET /clusters/{cluster_id}` derives members by created-at window, not actual cluster membership relation.
Evidence: `docs/spec.md:192`, `app/routers/clusters.py:151`, `app/routers/clusters.py:160`, `app/routers/clusters.py:177`
Root cause: No persisted `cluster_id`↔`ticket_id` membership model in current RCA writes.
Impact: Endpoint can return incorrect members; downstream RCA tooling receives inconsistent data.
Fix: Persist cluster membership at RCA write time and serve detail endpoint from that relation.

### ARCH-7 [P2] — Service/Transport Layering Violation
Symptom: Core service imports FastAPI exception type.
Evidence: `app/agent.py:15`
Root cause: HTTP mapping is implemented inside service layer.
Impact: Reuse/testing constraints and tighter framework coupling.
Fix: Raise domain errors in service; map to HTTP in route/adapters.

### ARCH-8 [P2] — Router Layer Contains Business Logic
Symptom: Route handlers perform authentication workflow and direct data/claim orchestration rather than delegating to services.
Evidence: `app/routers/auth.py:26`, `app/routers/auth.py:73`, `app/routers/auth.py:94`, `app/main.py:275`
Root cause: Service boundary for auth/webhook orchestration is incomplete.
Impact: Harder testability, mixed concerns, and increased drift risk.
Fix: Move auth + webhook orchestration logic into dedicated service layer; keep routers thin.

## Doc Patches Needed
| File | Section | Change |
|------|---------|--------|
| `docs/ARCHITECTURE.md` | `2.1 Component Status`, repository layout, security/auth sections | Add/refresh `JWTMiddleware`, auth router (`/auth/token`), RCA clusterer, metrics endpoint contract, and current `/approve` auth behavior (currently documented as unauthenticated). |
| `docs/spec.md` | `5. Security Assumptions`, `8. API Surface` | Reconcile real webhook/JWT policy and metrics exposure model; explicitly document `/metrics` vs `/metrics/cost` contract and protection boundary. |
| `docs/adr/002-vector-database.md` | `Decision`, `Consequences` | Update embedding model+dimension and ANN assumptions to runtime (Voyage/1024) or state rollback plan. |
| `docs/adr/003-rbac-design.md` (or audit gate docs) | Decision/status alignment | Resolve RS256-vs-HS256 contradiction across carry-forward finding and ADR text, with one explicit accepted target state. |
| `docs/adr/004-observability-stack.md` | Instrumentation scope | Clarify required RCA background span topology and acceptance criteria. |
| `docs/data-map.md` | Redis key schema | Align with implementation or keep as target and add explicit migration status/timeline for tenant-prefixed keys. |
---
