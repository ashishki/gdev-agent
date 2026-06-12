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
4. **Tenant visibility is isolated.** Grafana dashboards group by `tenant_hash`. A
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

### 2.7 Workflow Debug Map

| Workflow step | Question it answers | Metric signal | Trace/log signal | Dashboard panel |
|---------------|---------------------|---------------|------------------|-----------------|
| Signature and rate-limit | Did the request pass tenant HMAC and per-user throttles? | `gdev_requests_total{status=...}`, `gdev_request_duration_seconds{endpoint="/webhook"}` | `middleware.signature_check`, `middleware.rate_limit`, log `rate_limit_bypass` | Request Rate, Webhook Request Latency p50/p95/p99 |
| Dedup replay check | Was this webhook a replay, and did it avoid duplicate side effects? | `gdev_webhook_service_calls_total{method="handle",outcome="dedup_hit"}` | `middleware.dedup`, log `webhook_dedup_hit` | Request Rate and Failure Mode Signals |
| Input guard | Did unsafe input stop before any model call? | `gdev_guard_blocks_total{guard_type="input"}`, `gdev_injection_attempts_total` | `agent.input_guard`, log `guard_blocked` | Guard Block Rate |
| LLM classify/extract/draft | Is the provider slow, retrying, or returning malformed output? | `gdev_llm_requests_total`, `gdev_llm_duration_seconds`, `gdev_llm_retry_total`, `gdev_llm_tokens_total` | `agent.llm_classify`, `llm.api_call`, log `llm_call_complete` | LLM Latency p50/p95 and Failure Mode Signals |
| Approval route | Are risky actions being queued and reviewed? | `gdev_pending_total`, `gdev_approval_queue_depth`, `gdev_approved_total`, `gdev_rejected_total` | `agent.route`, `integration.telegram_notify`, log `pending_created` | Approval Workflow Outcomes and Pending Queue Depth |
| Execution and audit | Did safe/approved work complete with cost and audit evidence? | `gdev_llm_cost_usd_total`, `gdev_budget_utilization_ratio`, `gdev_budget_exceeded_total`, `gdev_integration_errors_total` | `db.ticket_insert`, `integration.linear_create`, log `action_executed` | LLM Cost, Budget Utilization Ratio, Failure Mode Signals |

All labels that identify a tenant use `tenant_hash`; the committed dashboard
uses Prometheus metrics with tenant-safe labels and does not query tenant tables
directly.

Failure-mode links from this map:

| Failure mode | Primary observability path |
|--------------|----------------------------|
| `FM_DUPLICATE_WEBHOOK_REPLAY` | `middleware.dedup`, `webhook_dedup_hit`, and `gdev_webhook_service_calls_total{outcome="dedup_hit"}`. |
| `FM_OUTPUT_GUARD_BLOCK` | `agent.output_guard`, `guard_blocked`, and `gdev_guard_blocks_total{guard_type="output"}`. |
| `FM_LLM_TIMEOUT` | `agent.llm_classify`, `llm.api_call`, `gdev_llm_requests_total{status="error"}`, and `gdev_llm_retry_total`. |
| `FM_BUDGET_EXCEEDED` | `agent.budget_check`, `gdev_budget_exceeded_total`, and `gdev_budget_utilization_ratio`. |
| `FM_APPROVAL_TTL_EXPIRED` | `agent.route`, `pending_expired`, and `gdev_approval_queue_depth`. |
| `FM_RATE_LIMIT_EXCEEDED` | `middleware.rate_limit`, request status `429`, and `gdev_requests_total{status="rate_limited"}`. |

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

## 4. Dashboard Export

The committed local dashboard export is
[`docker/grafana/provisioning/dashboards/gdev-agent.json`](../docker/grafana/provisioning/dashboards/gdev-agent.json).
It is provisioned by Docker Compose and covers the main support workflow:

| Dashboard panel | Primary debugging use |
|-----------------|-----------------------|
| Request Rate (RPS) | See webhook throughput by `tenant_hash` and status. |
| Webhook Request Latency p50/p95/p99 | Confirm request latency before splitting LLM/provider vs. app latency. |
| LLM Latency p50/p95 | Identify provider latency and retry symptoms. |
| Guard Block Rate | Spot input/output guard spikes and link to `FM_OUTPUT_GUARD_BLOCK`. |
| Pending Queue Depth | Detect human-review backlog and approval TTL risk. |
| Approval Workflow Outcomes | Compare pending, approved, and rejected volumes over the last hour. |
| Failure Mode Signals | Inspect budget exhaustion, LLM retry, and integration error spikes. |
| LLM Cost USD and Budget Utilization Ratio | Confirm budget pressure and `FM_BUDGET_EXCEEDED` behavior. |

The dashboard is local-review evidence. It is not a managed production
dashboard, and no external screenshots are claimed.

---

## 5. LLM Usage Logging

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

## 6. Cost Tracking

### 6.1 Real-time tracking
- Every `LLMClient.run_agent()` call updates `cost_ledger` (Postgres) atomically.
- `CostLedger.check_budget()` queries the daily row before each LLM call.
- `gdev_budget_utilization_ratio` gauge is updated after each ledger write.

### 6.2 Daily roll-up
- `CostAggregator` runs hourly: `SELECT SUM(cost_usd) FROM audit_log WHERE date = today GROUP BY tenant_id`.
- Results written to `cost_ledger` (upsert). This reconciles any missed real-time writes.

### 6.3 Budget alerts
- Alert fires when `gdev_budget_utilization_ratio` exceeds 0.8 (80 %).
- Second alert at 1.0 (100 %): requests begin returning HTTP 429 (budget exhausted).
- Tenant admin notified via Telegram (if configured) or email (future).

---

## 7. Alerting Strategy

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

The central local runbook is [SLO_RUNBOOK.md](SLO_RUNBOOK.md). It maps alerts and service symptoms
to stable failure-mode names from [FAILURE_MODES.md](FAILURE_MODES.md). Per-alert runbook files may
be added later if the project adds an externally operated deployment, but the current portfolio
scope keeps one canonical runbook.

| Signal | Failure taxonomy link | Primary runbook check |
|--------|-----------------------|-----------------------|
| `gdev_guard_blocks_total{guard_type="output"}` | `FM_OUTPUT_GUARD_BLOCK` | Inspect `agent.output_guard` span and unsafe-output eval cases. |
| `gdev_llm_requests_total{status="error"}` or `gdev_llm_retry_total` spike | `FM_LLM_TIMEOUT` | Check provider status, retry saturation, and whether any unsafe auto-execution occurred. |
| `gdev_budget_utilization_ratio >= 1.0` or `gdev_budget_exceeded_total` increments | `FM_BUDGET_EXCEEDED` | Verify the LLM call was blocked before spend and notify the tenant admin. |
| `gdev_approval_queue_depth > 20` or `pending_expired` spikes | `FM_APPROVAL_TTL_EXPIRED` | Inspect approval notification health and queue age. |
| `rate_limit_bypass` log event | `FM_REDIS_DEGRADED_RATE_LIMIT` | Restore Redis and consider temporary upstream throttling. |
| HTTP 429 from rate limiting | `FM_RATE_LIMIT_EXCEEDED` | Confirm retry delay behavior and traffic source. |
| Postgres connection or slow-query symptoms | `FM_POSTGRES_UNAVAILABLE` / `FM_POSTGRES_DEGRADED` | Check DB health, failed traces, and side-effect completion before replay. |

Local SLO targets for latency, error rate, approval queue behavior, guard blocks, and dependency
failure response are defined in [SLO_RUNBOOK.md](SLO_RUNBOOK.md). They are portfolio targets, not a
production SLA.
