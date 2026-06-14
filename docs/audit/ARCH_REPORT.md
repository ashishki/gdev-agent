# ARCH_REPORT — Cycle 17
_Date: 2026-06-14_

## Component Verdicts
| Component | Verdict | Note |
|-----------|---------|------|
| Tenant isolation proof | PASS | Canonical proof is bounded to local code, migrations, and tests; it explicitly excludes production/cloud/network controls. |
| RLS migrations and tenant DB context | PASS | Tenant-scoped tables have RLS policies, `gdev_admin` is the only bypass role, and runtime tenant context is transaction-local via `set_config(..., true)`. |
| JWT/RBAC boundary | PASS | Protected read/admin/approval APIs use JWT tenant/role context; current ADR accepts HS256 for v1, so P1-1 is not open under the accepted ADR. |
| Webhook signature boundary | PASS | `/webhook` tenant context is resolved from `X-Tenant-Slug` and per-tenant HMAC before downstream handling. |
| Approval boundary | PASS | `/approve` is JWT-role gated, optional approve-secret checked, and pending decisions are looked up/popped by JWT tenant namespace. |
| Secrets and cost separation | PASS | Webhook secrets stay per-tenant in encrypted Postgres rows, and cost ledger checks/writes are tenant-scoped. |
| Adversarial tenant scenarios | PASS | Audit-read, cross-tenant approval, missing/invalid slug, and invalid-HMAC examples are documented as local/test-backed boundaries. |
| Phase 6 compose and health shape | DRIFT | Compose has service health checks, but architecture docs still only describe a single `/health` probe and do not yet capture T21 readiness/liveness/migration-check framing. |
| Phase 6 secrets, backup, restore, config notes | DRIFT | T22 deployment-readiness notes are planned but not yet represented in architecture/evidence docs. |
| `app/services/*` layer integrity | PASS | Service modules do not import FastAPI symbols; the carry-forward `agent.py` `HTTPException` concern is absent. |
| `app/main.py` webhook/approve routes | PASS | Routes are thin adapters delegating to `WebhookService` and `ApprovalService`. |
| `app/routers/auth.py` | PASS | HTTP adapter delegates auth behavior to `AuthService`. |
| `app/routers/eval.py` | PASS | Router delegates eval trigger/list behavior to `EvalService`. |
| `app/routers/tickets.py` | DRIFT | Ticket read routes still contain SQL, pagination, 404 handling, and response assembly. |
| `app/routers/analytics.py` | DRIFT | Audit and cost routes still contain SQL, cursor parsing, pagination, and response assembly. |
| `app/routers/clusters.py` | DRIFT | Cluster routes still contain query construction, metrics, tracing, pagination, and response assembly. |
| `docs/ARCHITECTURE.md` current-state snapshot | DRIFT | Main architecture doc is stale relative to Cycle 17 eval/test/evidence and deployment-readiness scope. |
| `docs/spec.md` auth/production assumptions | DRIFT | Product spec still says all API calls, including `/webhook`, require JWT and that prod startup fails without legacy secrets; current architecture intentionally uses JWT-exempt signed webhooks and bounded local evidence. |

## ADR Compliance
| ADR | Verdict | Note |
|-----|---------|------|
| ADR-001 Storage | PASS | PostgreSQL remains the durable store with RLS; Redis remains TTL/ephemeral coordination and cache storage. |
| ADR-002 Vector DB | PASS | pgvector remains conditional; migration `0004` resizes vector columns to 1024, matching Voyage runtime and docs. |
| ADR-003 RBAC | PASS | P1-1 is closed under current ADR text: HS256 is the accepted v1 algorithm and RS256/JWKS is deferred to v2. |
| ADR-004 Observability | PASS | New service paths emit OTel-style spans and Prometheus metrics; `/metrics` network-scope caveat is documented. |
| ADR-005 Orchestration | PASS | Claude tool-use loop is bounded by `max_turns=5`; APScheduler remains the documented background-job model. |
| ADR-006 MCP | PASS | No MCP server was introduced; HTTP remains the product surface as decided. |

## Architecture Findings
### ARCH-1 [P2] — Read API Business Logic Remains In Route Handlers
Symptom: Read routes still violate the documented service-layer boundary by embedding SQL, pagination, metrics/tracing, error mapping, and response assembly directly in FastAPI router modules.

Evidence: `app/routers/tickets.py:57`, `app/routers/analytics.py:58`, `app/routers/clusters.py:118`

Root cause: Service extraction covered webhook, approval, auth, eval, and learning metrics, but ticket, audit/cost, and cluster read use cases were left in route handlers.

Impact: Tenant-scoped read behavior is harder to reuse and test outside HTTP, and future API changes risk duplicating pagination, error, metrics, and SQL logic.

Fix: Extract ticket, analytics, and cluster read behavior into service modules. Keep routers limited to dependency injection, role checks, request parameter validation, and service response translation.

### ARCH-2 [P2] — Main Architecture Snapshot Is Stale For Cycle 17
Symptom: `docs/ARCHITECTURE.md` still presents the system as a 2026-03-18 snapshot, lists the eval dataset as 25 cases, and omits current evidence-package language for the 272-test baseline, 180-case synthetic eval, tenant-isolation proof, load/observability evidence, and Phase 6 readiness positioning.

Evidence: `docs/ARCHITECTURE.md:34`, `docs/ARCHITECTURE.md:73`, `docs/audit/META_ANALYSIS.md:6`

Root cause: Focused hardening docs and README were updated through Phase 5, but the primary architecture contract has not been refreshed as the source-of-truth overview.

Impact: Reviewers see conflicting current-state claims across the repo, and `ARCH-HARDEN-1` remains open.

Fix: Refresh `docs/ARCHITECTURE.md` for Cycle 17: current status/date, eval/test evidence wording, local/pilot evidence boundaries, tenant-isolation proof entrypoint, observability/load docs, compose health framing, and remaining read-route debt.

### ARCH-3 [P2] — Spec Auth And Production-Secret Assumptions Lag Current Architecture
Symptom: `docs/spec.md` says all API calls require JWT and `/webhook` auth is HMAC plus JWT, while the current data map and implementation intentionally make `/webhook` JWT-exempt and tenant-resolved by signed slug plus HMAC. The spec also says `APPROVE_SECRET` and `WEBHOOK_SECRET` are required in production, while runtime currently warns for missing approve secret and deprecates legacy `WEBHOOK_SECRET`.

Evidence: `docs/spec.md:91`, `docs/spec.md:100`, `docs/spec.md:181`, `docs/data-map.md:234`

Root cause: Security design moved from legacy single-tenant secrets to per-tenant webhook secret lookup and local/pilot readiness boundaries, but `docs/spec.md` was not updated to match the accepted contract.

Impact: The product contract is ambiguous for reviewers and future implementers, especially around webhook ingress, production-readiness claims, and which controls are application-enforced versus deployment-scoped.

Fix: Update `docs/spec.md` to align with the current security model: protected REST APIs use JWT, webhook ingress uses per-tenant HMAC without JWT, `/metrics` is network-scoped, and production-grade secret/readiness hardening remains a Phase 6 documentation item unless implemented.

### ARCH-4 [P2] — Phase 6 Deployment-Readiness Architecture Is Not Yet Documented
Symptom: T21/T22 require compose migration checks, health/readiness/liveness behavior, secrets checklist, backup/restore notes, production-like config language, and explicit non-production-readiness boundaries, but the architecture docs currently only describe `/health` as a 200 liveness-style endpoint and README says deployment-readiness notes are not complete.

Evidence: `docs/audit/META_ANALYSIS.md:21`, `docs/ARCHITECTURE.md:483`, `README.md:224`

Root cause: Phase 6 work is next in the graph, and architecture docs have not yet been expanded from local stack description into deployment-readiness guidance.

Impact: Compose and health behavior are inspectable in `docker-compose.yml`, but reviewers do not yet have a single architecture/readiness page that distinguishes local proof, production-like config, backup/restore, and non-production boundaries.

Fix: Add or link a deployment-readiness section/document that covers compose migration verification, health/readiness/liveness semantics, secrets checklist, Postgres/Redis backup and restore notes, production-like local config, and known limitations without claiming production SaaS readiness.

## Doc Patches Needed
| File | Section | Change |
|------|---------|--------|
| `docs/ARCHITECTURE.md` | Header / Current System State | Refresh date, cycle state, component table, repository layout, eval/test counts, and current evidence links. |
| `docs/ARCHITECTURE.md` | Service Layer | Keep read-route extraction debt explicit, including tickets, analytics, and clusters. |
| `docs/ARCHITECTURE.md` | Health / Docker Stack / Deployment Readiness | Explain local compose dependency checks and distinguish liveness, readiness, and downstream dependency monitoring. |
| `docs/ARCHITECTURE.md` | Security / Environment Variables | Replace legacy `WEBHOOK_SECRET` wording with per-tenant encrypted webhook secret language and clarify `APPROVE_SECRET` behavior. |
| `docs/spec.md` | Security Assumptions / API Surface | Align JWT/HMAC rules with current webhook/JWT architecture and local/non-production readiness boundaries. |
| `docs/EVIDENCE_INDEX.md` | Known limits and production changes | Link the Phase 6 deployment-readiness notes once added. |
| `README.md` | Current State / Known Limits | Update recorded test baseline from 263 to the Cycle 17 272-pass baseline when verified in this cycle's final packaging. |
