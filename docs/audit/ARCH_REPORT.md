---
# ARCH_REPORT — Cycle 6
_Date: 2026-03-08_

## Component Verdicts
| Component | Verdict | Note |
|-----------|---------|------|
| `app/metrics.py` | PASS | Prometheus metric registry matches `docs/observability.md` metric contract (request/guard/LLM/budget/RCA/integration families present). |
| `app/main.py` | DRIFT | Middleware/auth contract drift vs docs: runtime stack includes `JWTMiddleware` and `/metrics`, but `docs/ARCHITECTURE.md` middleware diagram omits JWT and still describes legacy signature behavior. |
| `app/middleware/auth.py` | DRIFT | Security invariant mostly preserved (JWT + blocklist + tenant context), but `/webhook` is exempt from JWT while `docs/spec.md` states `/webhook` requires `HMAC sig + JWT`. |
| `app/middleware/signature.py` | DRIFT | Uses `X-Tenant-Slug` + `X-Webhook-Signature`; spec still states `X-Hub-Signature-256` and legacy `WEBHOOK_SECRET` model. |
| `app/middleware/rate_limit.py` | DRIFT | Rate-limit keys are not tenant-namespaced (`ratelimit:{user_id}` / `ratelimit_burst:{user_id}`), violating data-map/spec Redis isolation contract. |
| `app/jobs/rca_clusterer.py` | DRIFT | Prometheus RCA metrics are present, but no OTel spans for background RCA runs; `timeout=300` diverges from ADR-005 example `timeout=120` (undocumented rationale). |
| `app/routers/clusters.py` | VIOLATION | `GET /clusters/{cluster_id}` returns ticket IDs by time-window heuristic, not true cluster membership required by spec contract. |
| `app/agent.py` | VIOLATION | Service-layer boundary violation remains: `from fastapi import HTTPException` in core service module. |

## ADR Compliance
| ADR | Verdict | Note |
|-----|---------|------|
| ADR-001 Storage: PostgreSQL + RLS + Redis cache | DRIFT | Postgres + RLS are implemented, but Redis key namespace contract is not enforced across dedup/approval/rate-limit paths. |
| ADR-002 Vector DB: pgvector conditional | DRIFT | ADR still documents OpenAI + `VECTOR(1536)`; implementation/docs data map use Voyage + `VECTOR(1024)`. |
| ADR-003 RBAC: RS256 mandated | VIOLATION | Still open: implementation is HS256 (`jwt_algorithm = "HS256"`), no JWKS endpoint. |
| ADR-004 Observability: OTel spans + Prometheus in new services | DRIFT | Prometheus added for new paths (including RCA), but OTel background-job span topology remains incomplete (RCA job has no tracer spans). |
| ADR-005 Orchestration: Claude tool_use loop ≤5 turns | DRIFT | Tool loop ≤5 is implemented; scheduler exists. RCA timeout is 300s instead of ADR example 120s without ADR clarification. |

## Architecture Findings
### ARCH-1 [P1] — ADR-003 RS256 Requirement Still Open
Symptom: Auth stack still signs/verifies JWT with HS256 and does not expose JWKS.
Evidence: `app/config.py:49`, `app/routers/auth.py:94`, `app/middleware/auth.py:74`, `docs/adr/003-rbac-design.md:53`
Root cause: Deferred architecture decision (HS256 v1 simplification) never reconciled with accepted ADR.
Impact: ADR non-compliance persists on security-critical auth path; key distribution/rotation model differs from approved design.
Fix: Decide one path and document it: (a) amend ADR-003 to HS256 with explicit constraints, or (b) implement RS256 + `/auth/jwks.json`.

### ARCH-2 [P2] — Vector ADR Drift (1536/OpenAI vs 1024/Voyage)
Symptom: Accepted ADR-002 describes OpenAI 1536-dim embeddings, while current model/schema are Voyage 1024-dim.
Evidence: `docs/adr/002-vector-database.md:32`, `docs/adr/002-vector-database.md:36`, `docs/data-map.md:115`, `app/config.py:29`
Root cause: Model migration happened without ADR amendment.
Impact: Capacity assumptions, ANN sizing notes, and architecture docs are inconsistent.
Fix: Update ADR-002 decision and consequences to match Voyage/1024 (or revert implementation to ADR target).

### ARCH-3 [P2] — RCA Observability Incomplete (Metrics Yes, Traces Missing)
Symptom: RCA emits Prometheus metrics but no OpenTelemetry spans for background runs.
Evidence: `app/jobs/rca_clusterer.py:27`, `app/jobs/rca_clusterer.py:177`, `app/jobs/rca_clusterer.py:191`, `docs/observability.md:152`
Root cause: Metrics refactor landed without equivalent tracer instrumentation in RCA job path.
Impact: RCA execution cannot be traced end-to-end in Tempo/X-Ray; observability contract is only partially met.
Fix: Add root span(s) for RCA runs (`run_for_all_tenants` / `run_tenant`) with tenant-safe attributes.

### ARCH-4 [P2] — Middleware/Auth Contract Drift vs Spec
Symptom: Runtime auth/signature behavior diverges from spec contracts (`/webhook` JWT requirement and signature header name).
Evidence: `docs/spec.md:89`, `docs/spec.md:91`, `docs/spec.md:181`, `app/middleware/auth.py:52`, `app/middleware/signature.py:70`, `app/middleware/signature.py:109`
Root cause: Middleware refactor introduced per-tenant slug/signature flow but spec was not updated.
Impact: Security/integration expectations are ambiguous for callers and reviewers.
Fix: Align spec to implementation (or adjust middleware) and explicitly document `/webhook` auth contract.

### ARCH-5 [P2] — Redis Tenant Namespace Isolation Still Broken in Hot Paths
Symptom: Redis keys for dedup/pending/rate-limit are not prefixed by tenant.
Evidence: `docs/data-map.md:171`, `app/dedup.py:17`, `app/approval_store.py:25`, `app/middleware/rate_limit.py:95`
Root cause: Legacy key schema retained after multi-tenant architecture moved to mandatory tenant isolation.
Impact: Cross-tenant key collision risk and direct spec/data-map security drift.
Fix: Migrate key schema to `{tenant_id}:...` consistently; add compatibility migration/cleanup strategy.

### ARCH-6 [P2] — Cluster Detail API Does Not Return True Members
Symptom: Cluster detail endpoint infers ticket IDs by `first_seen/last_seen` window instead of cluster membership set.
Evidence: `docs/spec.md:192`, `app/routers/clusters.py:151`, `app/routers/clusters.py:160`, `app/routers/clusters.py:177`
Root cause: No persisted membership relation (`cluster_id` ↔ `ticket_id`) in current schema.
Impact: API can return false positives/negatives; consumers cannot trust cluster membership semantics.
Fix: Persist explicit membership (join table) during RCA upsert and serve that relation in `/clusters/{cluster_id}`.

### ARCH-7 [P2] — Service Layer Imports FastAPI Exception Type
Symptom: Core service module depends on FastAPI transport exception.
Evidence: `app/agent.py:15`
Root cause: Error mapping handled inside service instead of route boundary.
Impact: Layering rule violation; domain logic becomes framework-coupled and harder to reuse/test independently.
Fix: Raise domain exceptions in service; convert to `HTTPException` only in route/adapter layer.

## Doc Patches Needed
| File | Section | Change |
|------|---------|--------|
| `docs/ARCHITECTURE.md` | `2.1 Component Status` and `3. System Architecture` | Add `JWTMiddleware`, `/metrics` endpoint, Prometheus registry (`app/metrics.py`), RCA observability details; update middleware sequence and current signature contract (`X-Tenant-Slug` + `X-Webhook-Signature`). |
| `docs/spec.md` | `5. Security Assumptions`, `8. API Surface` | Reconcile `/webhook` auth contract with implementation (JWT exemption + per-tenant signature header scheme), or mark required code changes if spec remains authoritative. |
| `docs/adr/002-vector-database.md` | `Decision` and `Consequences` | Update embedding model/dimension from OpenAI 1536 to current Voyage 1024 (or document planned rollback). |
| `docs/adr/005-orchestration-model.md` | `Consequences` timeout note | Clarify why RCA timeout is 300s in implementation (`run_with_timeout`) versus 120s example. |
| `docs/data-map.md` | `3. Redis Key Schema` (if code-first) | If keeping current code temporarily, document deviation and migration plan; otherwise keep as-is and patch code to match schema contract. |
---
