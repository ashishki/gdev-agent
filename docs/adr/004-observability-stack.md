# ADR-004: Observability Stack — OpenTelemetry + Prometheus + Grafana

**Status:** Accepted
**Date:** 2026-03-03
**Deciders:** Architecture

---

## Context

The current system has structured JSON logging with request IDs, but no distributed tracing,
no metrics endpoint, and no alerting. Operational gaps:

- No way to know the p95 latency of the LLM call vs. the tool execution vs. the DB write.
- No tenant-scoped dashboards.
- No alerting on guard block rate spikes, cost overruns, or approval queue depth.
- No correlation between a log entry and the trace that caused it.

A real enterprise system needs answers to:
- Which tenant is generating the most cost?
- Is the LLM latency degrading over time?
- How often does the output guard block a response?
- Is the approval queue growing (humans not keeping up)?

---

## Decision

**Use OpenTelemetry (OTLP) for tracing, Prometheus for metrics, Loki for log aggregation,
and Grafana for dashboards and alerting. Self-hosted on Docker Compose for development;
AWS-compatible managed alternatives for production.**

### Components

| Concern | Tool | Rationale |
|---|---|---|
| Distributed traces | OpenTelemetry SDK + OTLP Collector | Vendor-neutral; no lock-in; Grafana Tempo or AWS X-Ray as backend |
| Application metrics | `prometheus_fastapi_instrumentator` + custom counters | FastAPI-native; well-understood |
| Log aggregation | Loki + Promtail (or CloudWatch in AWS) | Structured JSON logs; query with LogQL |
| Dashboards + alerts | Grafana | Single pane for traces, metrics, logs |
| Alerting | Grafana Alerting → Telegram/PagerDuty | Reuses existing Telegram integration |

### AWS Production Mapping

| Dev (Docker) | AWS Production |
|---|---|
| Grafana Tempo | AWS X-Ray (OTLP compatible) |
| Prometheus | Amazon Managed Prometheus (AMP) |
| Loki + Promtail | CloudWatch Logs |
| Grafana | Amazon Managed Grafana (AMG) |
| OTLP Collector | AWS Distro for OpenTelemetry (ADOT) |

The application code uses the OpenTelemetry SDK only; the backend can be swapped without
code changes by reconfiguring the OTLP exporter endpoint.

### Instrumentation Scope

**Traces** (span per pipeline stage):
```
http.request
  └── agent.input_guard
  └── agent.budget_check
  └── agent.llm_classify
        └── anthropic.api_call  (model, input_tokens, output_tokens as attributes)
  └── agent.propose_action
  └── agent.output_guard
  └── agent.route
  └── agent.embed (async; linked trace)
  └── db.ticket_insert
  └── integration.linear_create
```

Span attributes include `tenant_id` (hashed to avoid PII in traces), `category`, `urgency`,
`confidence`, `risky` flag.

**Metrics** (Prometheus, labeled by tenant_id_hash):
```
gdev_requests_total{status, category, urgency}
gdev_pending_total{tenant}
gdev_approved_total{tenant}
gdev_rejected_total{tenant}
gdev_guard_blocks_total{guard_type, tenant}
gdev_llm_tokens_total{direction, model, tenant}
gdev_llm_cost_usd_total{tenant}
gdev_llm_duration_seconds{tenant}  (histogram)
gdev_request_duration_seconds{endpoint}  (histogram)
gdev_approval_queue_depth{tenant}  (gauge)
gdev_rca_clusters_active{tenant}  (gauge)
gdev_budget_utilization_ratio{tenant}  (gauge, 0.0–1.0)
```

---

## Alternatives Considered

### Alternative A: Datadog
- **Pro:** Best-in-class UX; APM traces + logs + metrics in one product.
- **Con:** ~$50–200/host/month; vendor lock-in; overkill for a solo-engineer project.
  SDK instrumentation is Datadog-specific, making future migration costly.
- **Rejected for v1.** Viable for enterprise customers who bring their own Datadog account.

### Alternative B: AWS CloudWatch only (no Grafana/Prometheus)
- **Pro:** Zero additional services; all AWS-native; good integration with ECS/Lambda.
- **Con:** CloudWatch metrics are expensive for high cardinality (per-tenant labels).
  CloudWatch Insights for log queries is slow and limited. No native distributed tracing
  (X-Ray exists but UI is poor). No self-hostable equivalent for dev.
- **Rejected:** Developer experience is too poor; OpenTelemetry provides portability.

### Alternative C: Elastic Stack (ELK)
- **Pro:** Powerful log search; Kibana dashboards; good APM.
- **Con:** Very high resource footprint; complex to operate solo; not cost-effective at
  small scale; Elasticsearch license changes have created uncertainty.
- **Rejected.**

### Alternative D: No distributed tracing (logs only)
- **Con:** Impossible to diagnose multi-service latency issues. Cannot correlate a slow
  request with its LLM call, DB write, and integration call.
- **Rejected.** OpenTelemetry SDK overhead is ~1–2 ms per span; negligible.

---

## Consequences

**Positive:**
- Vendor-neutral instrumentation; backend swap requires only config changes.
- Developer-friendly: local Docker Compose runs full observability stack.
- Tenant-scoped dashboards show each studio's health independently.
- Grafana alerting triggers on guard spikes, cost overruns, approval queue depth.
- Log-trace correlation via `trace_id` injected into every log record.

**Negative / Risks:**
- Docker Compose becomes heavier (add OTLP Collector, Tempo, Prometheus, Loki, Grafana).
  Mitigate with an `--profile observability` flag so it's opt-in locally.
- Cardinality risk: `tenant_id` label on all metrics. Cap at 100 tenants for Prometheus.
  Beyond that, use metric aggregation or migrate to AMP.
- OpenTelemetry Python SDK adds ≈20 MB to dependencies. Acceptable.
