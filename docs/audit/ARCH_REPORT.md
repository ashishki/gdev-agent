# ARCH_REPORT — Cycle 16
_Date: 2026-06-12_

## Component Verdicts

| Component | Verdict | Note |
|-----------|---------|------|
| Load testing evidence | PASS | `docs/LOAD_TEST_REPORT.md` frames results as local deterministic/synthetic evidence and explicitly avoids production-capacity claims. |
| Load profile | DRIFT | `docs/load-profile.md` still contains infrastructure-scale expectations and future failure responses that are not fully represented by the committed deterministic harness. |
| Observability evidence | PASS | `docs/observability.md` maps support workflow steps to tenant-safe metric, trace, dashboard, and runbook signals. |
| Tenant isolation proof entrypoint | PASS | `docs/TENANT_ISOLATION.md` correctly scopes the proof to local tests and avoids claiming external production readiness. |
| `app/services/*` layer integrity | PASS | Services do not import FastAPI symbols; no carry-forward `HTTPException` import remains in `app/agent.py` or services. |
| `app/routers/auth.py` | PASS | Thin HTTP adapter; delegates login/logout/refresh behavior to `AuthService`. |
| `app/routers/eval.py` | PASS | Thin HTTP adapter for eval trigger/list operations; business behavior lives in `EvalService`. |
| `app/routers/analytics.py` | DRIFT | Audit and cost-list endpoints perform cursor parsing, SQL selection, pagination, and response assembly in the route handler. |
| `app/routers/tickets.py` | DRIFT | Ticket list/detail endpoints contain direct tenant-scoped SQL and pagination/404 behavior in the route handler. |
| `app/routers/clusters.py` | DRIFT | Cluster read routes contain query construction, metrics, tracing, pagination, and response assembly rather than delegating read use cases to a service. |

## ADR Compliance

| ADR | Verdict | Note |
|-----|---------|------|
| ADR-001 Storage | PASS | PostgreSQL remains the primary durable store, Redis is TTL/ephemeral, and the tenant isolation proof covers RLS-backed persistence. |
| ADR-002 Vector DB | PASS | pgvector remains the documented/implemented vector path, with no new vector-store drift in scope. |
| ADR-003 RBAC | PASS | P1-1 is no longer open as written: ADR-003 now accepts HS256 for v1 and explicitly defers RS256/JWKS to v2; implementation uses configurable `jwt_algorithm` defaulting to HS256. |
| ADR-004 Observability | PASS | New observability evidence covers Prometheus metrics, OTel-style spans, Grafana dashboard panels, and alert/runbook linkage with tenant-hash labels. |
| ADR-005 Orchestration | PASS | Claude tool-use loop remains bounded by `max_turns=5`; no new scheduler/orchestration model change in scope. |
| ADR-006 MCP | PASS | No MCP server was added; HTTP remains the only product surface. |

## Architecture Findings

### ARCH-1 [P2] — Read API Business Logic Remains In Route Handlers
Symptom: Several read APIs violate the documented service-layer boundary that "Routers are thin HTTP adapters" by embedding query, pagination, metrics, and response construction logic in route modules.

Evidence: `app/routers/tickets.py:57`, `app/routers/analytics.py:58`, `app/routers/clusters.py:118`

Root cause: The service-layer extraction has covered auth, eval, webhook, approval, and learning metrics, but ticket/audit/cost/cluster read models still live directly in FastAPI routers.

Impact: Authorization and tenant-scoped query behavior are harder to reuse and test outside HTTP handlers; future API shape changes risk duplicating pagination, error envelope, metrics, and SQL logic.

Fix: Move ticket, analytics, and cluster read use cases into service modules (`TicketService`, `AnalyticsService`, `ClusterReadService` or equivalent). Keep routers responsible for dependency injection, role checks, parameter validation, and service response translation only.

### ARCH-2 [P2] — Architecture Spec Still Describes An Older System Snapshot
Symptom: `docs/ARCHITECTURE.md` still presents the current system state as 2026-03-18, references an eval dataset of 25 cases, omits newer load/observability/tenant-isolation evidence, and still describes Google Sheets as the audit-log write path.

Evidence: `docs/ARCHITECTURE.md:34`, `docs/ARCHITECTURE.md:73`, `docs/ARCHITECTURE.md:635`

Root cause: Phase 4 evidence and later hardening work were added to focused docs, README, and tests without refreshing the main architecture snapshot.

Impact: Reviewers get inconsistent architecture claims: README says 260 tests and local evidence packages exist, while ARCHITECTURE.md still reads like an older milestone. This also carries forward `ARCH-HARDEN-1`.

Fix: Update `docs/ARCHITECTURE.md` to the Cycle 16 state: current test/eval wording, persistent audit path, observability/load evidence docs, tenant-isolation proof, and updated repository layout.

### ARCH-3 [P3] — Load Profile Mixes Portfolio Targets With Unproven Deployment Assumptions
Symptom: The load report is appropriately bounded, but `docs/load-profile.md` still includes concrete infrastructure sizing, p99 targets, connection-pool expectations, and remediation actions that are broader than the committed deterministic evidence.

Evidence: `docs/load-profile.md:11`, `docs/load-profile.md:43`, `docs/load-profile.md:51`, `docs/load-profile.md:86`

Root cause: The profile predates the bounded local deterministic report and still reads partly like a production load plan.

Impact: A reader may infer measured capacity or deployment readiness from the profile even though the report correctly says the committed artifact does not measure Redis/Postgres latency, memory, or one-hour soak behavior.

Fix: Split `docs/load-profile.md` into "target scenarios" and "measured local evidence" language, or add clear caveats near the topology and KPI sections that these are unvalidated targets until a live Locust run records infrastructure metrics.

## Doc Patches Needed

| File | Section | Change |
|------|---------|--------|
| `docs/ARCHITECTURE.md` | Current System State / Repository Layout | Refresh date, component table, repository tree, test/eval count language, and add load/observability/tenant-isolation evidence docs. |
| `docs/ARCHITECTURE.md` | Audit Log Entry | Replace stale Google Sheets-primary wording with Postgres primary audit plus optional Sheets export. |
| `docs/load-profile.md` | System Topology Assumptions / Scenario KPIs | Mark infrastructure sizing, p99, connection pool, and remediation values as target assumptions, not measured evidence. |
