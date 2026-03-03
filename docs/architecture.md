# Architecture v1.0 — Enterprise AI Ticket Governance Platform

_Evolves from ARCHITECTURE.md v2.1 · Incremental expansion, no redesign._
_Date: 2026-03-03_

---

## 1. Component Diagram (Textual)

```
┌─────────────────────────────────────────────────────────────────┐
│  External Boundary                                              │
│                                                                 │
│  n8n workflows ──┐                                              │
│  Telegram Bot  ──┼──► [API Gateway]                            │
│  Direct HTTP   ──┘    - TLS termination                        │
│                        - JWT validation (RS256)                 │
│                        - Tenant ID injection into request ctx   │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  gdev-agent FastAPI Service                                     │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Middleware Stack (ordered)                              │   │
│  │  1. RequestIDMiddleware  — injects trace-correlated ID  │   │
│  │  2. TenantMiddleware     — resolves tenant from JWT     │   │
│  │  3. SignatureMiddleware  — HMAC-SHA256 verification     │   │
│  │  4. RateLimitMiddleware  — sliding window per user/IP   │   │
│  │  5. DedupMiddleware      — 24 h message_id idempotency  │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  AgentPipeline (per-request, synchronous)               │   │
│  │                                                         │   │
│  │  InputGuard                                             │   │
│  │    ├── length check                                     │   │
│  │    ├── injection pattern scan                           │   │
│  │    └── PII pre-redaction (names/emails/IPs)             │   │
│  │         │                                               │   │
│  │         ▼                                               │   │
│  │  LLMClient (Claude tool_use loop, ≤ 5 turns)           │   │
│  │    ├── classify (category, urgency, confidence)         │   │
│  │    ├── extract (transaction_id, platform, error_code)   │   │
│  │    └── draft_response                                   │   │
│  │         │                                               │   │
│  │         ▼                                               │   │
│  │  ActionProposer                                         │   │
│  │    ├── risk scoring (category rules + keyword scan)     │   │
│  │    └── ProposedAction with risky flag                   │   │
│  │         │                                               │   │
│  │         ▼                                               │   │
│  │  OutputGuard                                            │   │
│  │    ├── secret scan (regex patterns)                     │   │
│  │    ├── URL allowlist enforcement                        │   │
│  │    └── confidence floor check                           │   │
│  │         │                                               │   │
│  │         ▼                                               │   │
│  │  Router                                                 │   │
│  │    ├── risky=False → ToolRegistry.execute()             │   │
│  │    └── risky=True  → ApprovalStore.put_pending()        │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Supporting Services                                    │   │
│  │  EventStore       — Postgres write (ticket, audit)      │   │
│  │  EmbeddingService — pgvector upsert after triage        │   │
│  │  CostLedger       — per-tenant token accounting         │   │
│  │  TenantRegistry   — cached tenant config (Redis TTL)    │   │
│  └─────────────────────────────────────────────────────────┘   │
└──────────────────┬──────────────────────────────────────────────┘
                   │
        ┌──────────┼──────────────────────┐
        │          │                      │
        ▼          ▼                      ▼
   [Redis]    [Postgres + pgvector]  [Anthropic API]
   - dedup    - tenants              - claude-sonnet-4-6
   - pending  - tenant_users
   - rate lim - tickets
   - config   - classifications
     cache    - audit_log
              - embeddings
              - clusters
              - cost_ledger
              - agent_configs

        │
        ▼
┌───────────────────────────────────────┐
│  Background Workers (same process,    │
│  APScheduler; extract to Celery if    │
│  load demands it)                     │
│                                       │
│  RCAClusterer   — every 15 min        │
│    pgvector ANN query → DBSCAN        │
│    → ClusterSummary upsert            │
│                                       │
│  CostAggregator — every 1 h           │
│    roll up token counts per tenant    │
│    → alert if > 80 % of budget        │
│                                       │
│  EvalRunner     — on-demand or daily  │
│    run eval/cases.jsonl per tenant    │
│    → EvalRun record                   │
└───────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────┐
│  Observability Stack                  │
│  OTLP → Tempo  (distributed traces)   │
│  Prometheus scrape (metrics)          │
│  Loki  (log aggregation)              │
│  Grafana (dashboards + alerts)        │
└───────────────────────────────────────┘
```

---

## 2. Data Flow

### 2.1 Happy Path (auto-execute)

```
POST /webhook
  → Middleware stack (sig check, rate limit, dedup)
  → InputGuard — pass
  → LLMClient.run_agent()
      → Claude API call (tool_use)
      → classify tool result
      → extract tool result
      → draft_response
  → ActionProposer → risky=False
  → OutputGuard — pass
  → ToolRegistry.execute("create_ticket_and_reply")
      → Postgres INSERT tickets + classifications
      → EmbeddingService.upsert(ticket_id, text_embedding)
      → Linear.create_issue() [if configured]
      → Telegram.send_reply() [if configured]
  → CostLedger.record(tenant_id, input_tokens, output_tokens)
  → AuditLog.append(...)
  → return WebhookResponse(status="executed")
```

### 2.2 HITL Path (approval required)

```
POST /webhook
  → ... same up to ActionProposer → risky=True
  → OutputGuard — pass
  → ApprovalStore.put_pending()
      → Redis SETEX pending:{tenant_id}:{pending_id}
      → Postgres INSERT pending_decisions (permanent record)
  → Telegram.send_approval_request() [async, non-blocking]
  → AuditLog.append(status="pending")
  → return WebhookResponse(status="pending")

POST /approve
  → JWT auth → role check (support_agent+)
  → ApprovalStore.pop_pending(pending_id)
      → Redis GETDEL
  → if approved:
      → ToolRegistry.execute(action)
      → Postgres INSERT approval_events(reviewer, decision, latency)
      → AuditLog.append(status="approved")
  → if rejected:
      → Postgres INSERT approval_events(reviewer, decision="rejected")
      → AuditLog.append(status="rejected")
```

### 2.3 Root Cause Analysis (background)

```
RCAClusterer (every 15 min per tenant):
  → SELECT ticket_embeddings WHERE created_at > now() - window
  → pgvector ANN → similarity graph
  → DBSCAN clustering (eps=0.15, min_samples=3)
  → for each cluster:
      → LLMClient.summarize_cluster(sample_texts)
      → UPSERT cluster_summaries
  → Telegram.notify_admin(clusters_changed) [if configured]
```

---

## 3. Agent Pipeline Stages

| Stage | Component | Input | Output | Guardrail |
|---|---|---|---|---|
| 1. Input validation | `InputGuard` | Raw text | Validated text or ValueError | Length, injection patterns, PII pre-check |
| 2. Budget check | `CostLedger.check_budget()` | `tenant_id` | Allow/deny | Reject if tenant at 100 % daily budget |
| 3. Classify + extract | `LLMClient.run_agent()` | Validated text | `TriageResult` (classification, extracted, draft) | ≤ 5 tool-use turns |
| 4. Action proposal | `ActionProposer.propose()` | `TriageResult` + config | `ProposedAction` (with risk score) | Category rules, keyword scan, confidence threshold |
| 5. Output guard | `OutputGuard.scan()` | Draft text + action | Redacted draft, possibly blocked | Secret scan, URL allowlist, confidence floor |
| 6. Route / pend | `Router` | `ProposedAction` | Executed result or PendingDecision | Risk flag check |
| 7. Embed | `EmbeddingService.upsert()` | Ticket text | pgvector row | Async, after response sent |
| 8. Cost record | `CostLedger.record()` | Token counts | Updated ledger | Budget alert if threshold crossed |

---

## 4. Failure Handling Strategy

### 4.1 LLM failures

- Network errors or 5xx from Anthropic API: retry with exponential backoff (tenacity), max 3 attempts.
- After 3 failures: return HTTP 503 to caller. Do not create a ticket. Log structured event.
- Confidence too low after tool-use loop: route to pending (force human review) rather than reject.
- Token budget exceeded mid-turn: truncate loop, return partial result with `confidence=0.0`,
  force pending.

### 4.2 Approval store failures

- Redis unavailable: fall back to Postgres-only pending store. Log degraded mode.
- Expired pending (TTL elapsed): `pop_pending` returns None → 404 to caller. Postgres record retained.
- Double-approve race: `GETDEL` atomicity prevents double execution.

### 4.3 Integration failures (Linear, Telegram)

- Linear API timeout: retry 2x, then log and return `action_result.status="integration_failed"`.
  Ticket is still created in Postgres; Linear sync can be retried manually.
- Telegram approval notification failure: non-fatal. Log warning with `exc_info`. Approval still
  accessible via REST API.

### 4.4 Postgres failures

- Write failures: return HTTP 500. Do not swallow. Let caller retry (dedup cache prevents duplicate
  processing on retry).
- Read failures on GET endpoints: return HTTP 503 with `Retry-After: 30`.

### 4.5 Background worker failures

- RCAClusterer crash: APScheduler logs exception, reschedules at next interval. No data loss.
- CostAggregator miss: next run recalculates from ledger; idempotent.

### 4.6 Multi-tenant isolation failures

- Tenant not found in registry: reject with HTTP 401. Do not fall through to default tenant.
- RLS violation: Postgres raises exception → caught → HTTP 500 + structured log. Never silently
  return cross-tenant data.

---

## 5. Observability Layer Placement

```
Middleware stack
  RequestIDMiddleware
    └─ starts OTLP span: "http.request"
       attaches trace_id to REQUEST_ID context var

AgentPipeline
  each stage is a child span:
    "agent.input_guard"
    "agent.budget_check"
    "agent.llm_classify"    ← includes LLM latency, token counts as span attributes
    "agent.propose_action"
    "agent.output_guard"
    "agent.route"
    "agent.embed"           ← async, separate span

Prometheus counters (labels: tenant_id, category, urgency, status):
  gdev_requests_total
  gdev_pending_total
  gdev_approved_total
  gdev_rejected_total
  gdev_guard_blocks_total{guard_type="input"|"output"}
  gdev_llm_tokens_total{direction="input"|"output"}
  gdev_llm_cost_usd_total
  gdev_integration_errors_total{integration="linear"|"telegram"|"sheets"}

Prometheus histograms:
  gdev_request_duration_seconds{endpoint}
  gdev_llm_duration_seconds
  gdev_embedding_duration_seconds

Logs (JSON, structured):
  every pipeline event emits:
    trace_id, span_id, tenant_id, request_id, event, context{}
  no PII in log fields (user_id is hashed)
```

---

## 6. Incremental Migration Path

The existing single-tenant architecture is preserved. Multi-tenant support is layered in:

1. **Phase 1** (week 1–2): Add Postgres. Migrate audit log from Google Sheets → Postgres.
   Add `tenant_id` column (single default tenant). Middleware reads tenant from JWT header.
2. **Phase 2** (week 2–3): Add pgvector. EmbeddingService runs after every triage. RCA
   clusterer background job.
3. **Phase 3** (week 3–4): RBAC. TenantUser table. JWT roles enforced on every endpoint.
   RLS policies applied to all tenant-scoped tables.
4. **Phase 4** (week 4–5): Agent registry. Cost ledger and budget enforcement. Eval REST
   endpoint.
5. **Phase 5** (week 5–6): Observability wiring (OTLP, Prometheus, Grafana dashboards).
   Load testing. Hardening.
