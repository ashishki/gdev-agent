# Observability Strategy v1.0

_Date: 2026-03-03 · See ADR-004 for the decision rationale behind this stack._

---

## 1. Principles

1. **No PII in telemetry.** User IDs in spans and metrics are SHA-256 hashes. Raw text never
   appears in trace attributes, metric labels, or log fields.
2. **Every request produces a trace.** No sampling in development. In production, sample at
   100 % for error traces, 10 % for success traces (head-based sampling at OTLP Collector).
3. **Logs and traces are correlated.** Every log record contains `trace_id` and `span_id`
   from the active OpenTelemetry context.
4. **Tenant visibility is isolated.** Grafana dashboards filter by `tenant_id_hash`. A
   tenant admin sees only their own data.
5. **Alerting is actionable.** Every alert maps to a specific runbook or remediation step.
   No alert without a clear owner and SLA.

---

## 2. Metrics to Collect

### 2.1 Request metrics

| Metric | Type | Labels | Description |
|---|---|---|---|
| `gdev_requests_total` | Counter | `status`, `category`, `urgency`, `tenant_hash` | All webhook requests by outcome |
| `gdev_request_duration_seconds` | Histogram | `endpoint`, `tenant_hash` | End-to-end request latency |
| `gdev_pending_total` | Counter | `tenant_hash` | Actions that required human approval |
| `gdev_approved_total` | Counter | `tenant_hash` | Actions approved by humans |
| `gdev_rejected_total` | Counter | `tenant_hash` | Actions rejected by humans |
| `gdev_approval_queue_depth` | Gauge | `tenant_hash` | Current pending decisions not yet resolved |

### 2.2 Guard metrics

| Metric | Type | Labels | Description |
|---|---|---|---|
| `gdev_guard_blocks_total` | Counter | `guard_type` (`input`/`output`), `reason`, `tenant_hash` | Guard block events |
| `gdev_guard_redactions_total` | Counter | `guard_type`, `tenant_hash` | Redactions (non-blocking) |
| `gdev_injection_attempts_total` | Counter | `tenant_hash` | Input injection pattern hits |

### 2.3 LLM metrics

| Metric | Type | Labels | Description |
|---|---|---|---|
| `gdev_llm_requests_total` | Counter | `model`, `status` (`ok`/`error`/`retry`), `tenant_hash` | LLM API calls |
| `gdev_llm_duration_seconds` | Histogram | `model`, `tenant_hash` | LLM round-trip time |
| `gdev_llm_tokens_total` | Counter | `direction` (`input`/`output`), `model`, `tenant_hash` | Token consumption |
| `gdev_llm_cost_usd_total` | Counter | `model`, `tenant_hash` | LLM cost in USD |
| `gdev_llm_turns_used` | Histogram | `tenant_hash` | Tool-use turns consumed per request |
| `gdev_llm_retry_total` | Counter | `tenant_hash` | LLM retries triggered |

### 2.4 Cost and budget metrics

| Metric | Type | Labels | Description |
|---|---|---|---|
| `gdev_budget_utilization_ratio` | Gauge | `tenant_hash` | Current day cost / daily budget (0.0–1.0) |
| `gdev_budget_exceeded_total` | Counter | `tenant_hash` | Requests blocked due to budget exhaustion |

### 2.5 RCA and clustering metrics

| Metric | Type | Labels | Description |
|---|---|---|---|
| `gdev_rca_clusters_active` | Gauge | `tenant_hash` | Active cluster count after latest run |
| `gdev_rca_run_duration_seconds` | Histogram | `tenant_hash` | RCA clusterer job duration |
| `gdev_rca_tickets_scanned` | Counter | `tenant_hash` | Tickets processed in RCA runs |
| `gdev_embedding_duration_seconds` | Histogram | `tenant_hash` | Embedding upsert latency |

### 2.6 Integration metrics

| Metric | Type | Labels | Description |
|---|---|---|---|
| `gdev_integration_errors_total` | Counter | `integration` (`linear`/`telegram`/`sheets`), `tenant_hash` | Integration failure count |
| `gdev_integration_duration_seconds` | Histogram | `integration`, `tenant_hash` | Integration call latency |

---

## 3. Traces

### 3.1 Span Hierarchy

```
http.request  [root span]
  attributes:
    http.method, http.route, http.status_code
    tenant_id_hash, request_id

  ├── middleware.signature_check
  ├── middleware.rate_limit
  ├── middleware.dedup
  │
  ├── agent.input_guard
  │     attributes: text_length, blocked (bool)
  │
  ├── agent.budget_check
  │     attributes: budget_utilization_ratio, allowed (bool)
  │
  ├── agent.llm_classify
  │     attributes: model, input_tokens, output_tokens, cost_usd,
  │                 turns_used, category, urgency, confidence
  │     ├── llm.api_call [turn 1]
  │     ├── llm.api_call [turn 2] (if multi-turn)
  │     └── tool.lookup_faq (if called)
  │
  ├── agent.propose_action
  │     attributes: risky (bool), risk_reason, tool
  │
  ├── agent.output_guard
  │     attributes: blocked (bool), redacted (bool), url_stripped (bool)
  │
  ├── agent.route
  │     attributes: outcome (executed/pending)
  │
  ├── db.ticket_insert  (if executed)
  ├── integration.linear_create  (if configured)
  └── integration.telegram_notify  (if pending)

[async, linked trace]
agent.embed
  attributes: model_version, embedding_dim, latency_ms
```

### 3.2 Trace Propagation

- Incoming requests: extract `traceparent` header if present (n8n or upstream caller supports W3C
  Trace Context). If absent, generate a new root trace.
- `trace_id` is added to every log record via the `RequestIDMiddleware`.
- Background jobs (RCA, cost aggregator) start their own root traces.

---

## 4. LLM Usage Logging

Every LLM call emits a structured log event immediately after the API response:

```json
{
  "event": "llm_call_complete",
  "trace_id": "...",
  "tenant_id_hash": "...",
  "model": "claude-sonnet-4-6",
  "prompt_version": "triage-v1.0",
  "input_tokens": 412,
  "output_tokens": 87,
  "cost_usd": 0.00254,
  "latency_ms": 1240,
  "turns": 2,
  "status": "ok",
  "category": "billing",
  "confidence": 0.91,
  "timestamp": "2026-03-03T12:00:00Z"
}
```

No prompt text or response text is logged. Token counts and metadata only.

---

## 5. Cost Tracking

### 5.1 Real-time tracking
- Every `LLMClient.run_agent()` call updates `cost_ledger` (Postgres) atomically.
- `CostLedger.check_budget()` queries the daily row before each LLM call.
- `gdev_budget_utilization_ratio` gauge is updated after each ledger write.

### 5.2 Daily roll-up
- `CostAggregator` runs hourly: `SELECT SUM(cost_usd) FROM audit_log WHERE date = today GROUP BY tenant_id`.
- Results written to `cost_ledger` (upsert). This reconciles any missed real-time writes.

### 5.3 Budget alerts
- Alert fires when `gdev_budget_utilization_ratio` exceeds 0.8 (80 %).
- Second alert at 1.0 (100 %): requests begin returning HTTP 429 (budget exhausted).
- Tenant admin notified via Telegram (if configured) or email (future).

---

## 6. Alerting Strategy

All alerts route to Grafana Alerting → Telegram channel or PagerDuty (configurable).

| Alert | Condition | Severity | Action |
|---|---|---|---|
| High guard block rate | `gdev_guard_blocks_total` rate > 5/min for a tenant | WARNING | Check for abuse or mis-configuration |
| Output guard blocking responses | `gdev_guard_blocks_total{guard_type="output"}` > 0 in 5 min | CRITICAL | LLM generating dangerous output; review prompt |
| LLM error rate elevated | `gdev_llm_requests_total{status="error"}` rate > 10 % | WARNING | Check Anthropic status; retry saturation |
| LLM p99 latency spike | `histogram_quantile(0.99, gdev_llm_duration_seconds)` > 10 s | WARNING | LLM degradation; check Anthropic status |
| Budget at 80 % | `gdev_budget_utilization_ratio` > 0.8 for any tenant | INFO | Notify tenant admin |
| Budget exhausted | `gdev_budget_utilization_ratio` >= 1.0 | CRITICAL | Requests blocked; escalate to tenant admin |
| Approval queue depth rising | `gdev_approval_queue_depth` > 20 for any tenant | WARNING | Humans not reviewing; notify support_agent team |
| API p99 > 5 s | `histogram_quantile(0.99, gdev_request_duration_seconds)` > 5 | WARNING | Investigate trace for bottleneck |
| Postgres connection failure | `gdev_integration_errors_total{integration="postgres"}` > 0 | CRITICAL | Database degraded; check RDS |
| RCA clusterer not running | `gdev_rca_run_duration_seconds` absent for > 20 min | WARNING | Scheduler may have crashed |

### Alert runbooks
Each alert links to a `docs/runbooks/{alert-name}.md` file (to be created during Phase 5).
