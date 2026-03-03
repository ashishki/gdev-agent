# Enterprise AI Ticket Governance & Root Cause Intelligence Platform
## System Specification v1.0

_Owner: Architecture · Status: DRAFT · Date: 2026-03-03_
_This document is the authoritative contract for product scope. All implementation work must trace to a section here._

---

## 1. Problem Definition

Game studios running live-service titles receive thousands of player support messages per day across
multiple channels (in-game, Discord, Telegram, email). Current reality:

- Manual triage introduces 2–8 h classification lag.
- Support agents spend 60–70 % of time on repetitive, low-skill routing decisions.
- Root causes of bug spikes and billing disputes are identified reactively, hours or days after they
  are detectable in ticket volume patterns.
- Studios with multiple titles or regions have no shared governance layer; each product runs its own
  ad-hoc tooling.
- Compliance obligations (GDPR data retention, audit trails for financial disputes) are handled
  inconsistently across tenants.

**Core pain**: There is no authoritative, observable, auditable AI layer that can classify, route,
and cluster player support at scale while giving human operators meaningful oversight and override
capability.

---

## 2. System Scope

**In scope:**

1. Receive support requests via webhook (n8n, Telegram, direct HTTP, or any HTTP caller).
2. Multi-tenant isolation: each studio (tenant) is a separate data boundary.
3. RBAC: three roles — `tenant_admin`, `support_agent`, `viewer`.
4. AI pipeline: input guard → classify → extract → propose action → output guard → route/escalate.
5. Human-in-the-loop (HITL): pending approvals surfaced via Telegram or approval UI; override tracked.
6. Persistent audit log (Postgres) replacing the current Google Sheets append.
7. Semantic duplicate and cluster detection using vector embeddings (pgvector).
8. Root Cause Analyzer: a background job that clusters similar tickets over a rolling window and
   surfaces the top-N emerging issues to tenant admins.
9. Observability: structured logs (JSON), OpenTelemetry traces, Prometheus metrics.
10. Evaluation harness (extend existing `eval/runner.py`) with per-tenant accuracy baselines.
11. LLM cost budget enforcement per tenant per billing period.
12. Agent registry: versioned, declarative registry of all agent configurations.
13. REST API for all reads (ticket history, cluster summaries, audit, metrics).

**Out of scope (v1):**

- Chat UI / customer-facing portal.
- Real-time streaming responses.
- Model fine-tuning or RAG over full ticket corpus (pgvector covers semantic search; full RAG deferred).
- Custom LLM hosting; Anthropic API only.
- Billing integration (usage quotas tracked, invoicing deferred).
- Native mobile SDKs.

---

## 3. Non-Goals

- This is not a general-purpose chatbot framework.
- This is not a customer relationship management (CRM) system; it augments existing CRM tools.
- This does not replace n8n or any existing workflow orchestrator; it remains a webhook-driven service.
- Auto-remediation of live game bugs is not in scope; the system routes and escalates, it does not
  execute game server operations.

---

## 4. SLA Assumptions

| Metric | Target |
|---|---|
| Webhook p99 latency (triage + route) | < 3 s |
| Approval notification delivery | < 30 s after pending created |
| Classification accuracy (per tenant eval baseline) | ≥ 0.85 F1 |
| Input guard block rate on known injection patterns | 1.00 |
| Output guard secret leak rate | 0.00 |
| System availability (API uptime) | 99.5 % monthly |
| Pending action TTL | Configurable; default 3600 s |
| Root Cause Analyzer refresh cadence | Every 15 min (configurable per tenant) |
| Cost per request | ≤ $0.015 (enforced via budget guard) |

SLA targets are per-tenant; degraded performance in one tenant must not cascade to others.

---

## 5. Security Assumptions

1. All inbound webhooks are authenticated via HMAC-SHA256 (`X-Hub-Signature-256`). Secret is
   per-tenant; rotation requires no downtime (dual-secret window of 60 s).
2. All API calls require a JWT Bearer token. JWTs encode `tenant_id` and `role`.
3. Postgres row-level security (RLS) enforces tenant isolation at the database layer; no application
   code path must bypass RLS.
4. Redis namespaces are prefixed with `{tenant_id}:` to prevent cross-tenant key collisions.
5. PII in player messages (names, emails, transaction IDs) is hashed (SHA-256) before storage in
   audit tables. Raw text is stored only in the `tickets` table under RLS.
6. The Anthropic API key is global (single key), but per-tenant usage is tracked and quotas enforced
   before the API call is made.
7. All service-to-service calls within the stack use mTLS in production.
8. `APPROVE_SECRET` and `WEBHOOK_SECRET` are required in production; startup fails if absent.
9. Secrets are injected via environment variables only; no secrets in config files or logs.
10. Output guard runs on every LLM response before it leaves the service boundary.

---

## 6. High-Level Architecture

```
[External Callers]
  n8n / Telegram / Direct HTTP
        │
        ▼
[API Gateway / Load Balancer]
  HTTPS termination, JWT validation
        │
        ▼
[gdev-agent FastAPI Service]
  ┌─────────────────────────────────────────┐
  │  Middleware stack                        │
  │  HMAC sig check → Rate limit → Dedup    │
  │                                         │
  │  AgentPipeline                          │
  │  InputGuard → Classify → Extract →      │
  │  Propose → OutputGuard → Route          │
  │                                         │
  │  HITL layer                             │
  │  PendingStore → Approval API            │
  └─────────────────────────────────────────┘
        │              │              │
        ▼              ▼              ▼
   [Redis]        [Postgres]    [Anthropic API]
   dedup          tickets        Claude Sonnet
   rate limit     audit log
   pending        tenants
                  RBAC
                  embeddings (pgvector)
        │
        ▼
  [Background Workers]
  RCA Clusterer (APScheduler / Celery)
  Cost Aggregator
  Eval Runner
        │
        ▼
  [Observability]
  OTLP Collector → Tempo (traces)
                 → Prometheus (metrics)
                 → Loki (logs)
  Grafana dashboard
```

---

## 7. Core Entities

| Entity | Description |
|---|---|
| `Tenant` | Isolated studio account. Has settings, webhook secret, cost budget. |
| `TenantUser` | Human operator. Belongs to one tenant, has one role. |
| `Ticket` | Single player support request. Immutable after creation. |
| `TicketClassification` | Classification result attached to a Ticket. Versioned per agent run. |
| `ExtractedFields` | Structured fields pulled from ticket text. Linked to Ticket. |
| `ProposedAction` | Action the agent proposes. May be auto-executed or pended. |
| `PendingDecision` | HITL record. TTL-gated, stored in Redis (short-lived) + Postgres (permanent audit). |
| `ApprovalEvent` | Immutable record of approve/reject decision with reviewer identity. |
| `AuditLogEntry` | Immutable record of every pipeline execution with cost, latency, outcome. |
| `TicketEmbedding` | Vector embedding of ticket text. Stored in pgvector for cluster queries. |
| `ClusterSummary` | Aggregated root cause cluster: N tickets, common theme, severity. |
| `AgentConfig` | Versioned agent configuration record (model, tools, guardrail settings). |
| `CostLedger` | Daily per-tenant LLM cost roll-up. |
| `EvalRun` | Snapshot of evaluation run: accuracy, block rate, cost. |

---

## 8. API Surface

### Inbound (existing, extended)

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/webhook` | HMAC sig + JWT | Submit player support request |
| `POST` | `/approve` | JWT (support_agent+) | Approve or reject pending action |
| `GET` | `/health` | None | Liveness probe |

### New endpoints (v1 evolution)

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/tickets` | JWT | Paginated ticket list for tenant |
| `GET` | `/tickets/{ticket_id}` | JWT | Single ticket with classification + audit trail |
| `GET` | `/clusters` | JWT | Active root cause clusters for tenant |
| `GET` | `/clusters/{cluster_id}` | JWT | Cluster detail with member tickets |
| `GET` | `/audit` | JWT (tenant_admin) | Paginated audit log |
| `GET` | `/metrics/cost` | JWT (tenant_admin) | Cost summary by day/period |
| `GET` | `/agents` | JWT (tenant_admin) | Agent registry for tenant |
| `PUT` | `/agents/{agent_id}` | JWT (tenant_admin) | Update agent config (triggers version bump) |
| `POST` | `/eval/run` | JWT (tenant_admin) | Trigger eval run against baseline dataset |
| `GET` | `/eval/runs` | JWT | List eval run history |

All responses: `application/json`. Pagination via `?cursor=` + `?limit=`. Error envelope:
`{"error": {"code": "...", "message": "..."}}`.

---

## 9. Evaluation Criteria

| Criterion | Measurement |
|---|---|
| Classification accuracy | F1 per category on `eval/cases.jsonl`, per tenant |
| Guard effectiveness | Injection block rate = 1.0 on adversarial set |
| Output safety | Zero secret leaks on canary set |
| Latency | p50/p95/p99 per endpoint via Prometheus histograms |
| Cost | USD/request, USD/day per tenant; alert at 80 % of budget |
| HITL rate | % of requests requiring human approval (target: < 20 %) |
| Override rate | % of approvals where human rejects agent proposal |
| Cluster coverage | % of tickets assigned to a named cluster within 15 min |
| Eval regression | No eval run may drop F1 by > 0.02 vs. prior run without alert |

---

## 10. Definition of Done

A feature is done when:

1. Implementation matches this spec's entity and API contracts.
2. Unit tests cover the happy path and at least two failure modes.
3. Eval run passes (F1 ≥ 0.85, guard block rate = 1.0).
4. All new endpoints documented in this spec with request/response schemas.
5. New ADR drafted if a structural decision was made.
6. Observability: new code emits at least one trace span and one counter increment.
7. No secrets in code or logs (verified by output guard canary test).
8. `docs/PLAN.md` PR entry marked Delivered.
9. `docs/devlog-template.md` entry created if a bug or architecture change occurred.
