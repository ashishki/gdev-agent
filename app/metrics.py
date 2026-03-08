"""Prometheus metrics registry for application observability."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, generate_latest

REQUESTS_TOTAL = Counter(
    "gdev_requests_total",
    "All webhook requests by outcome",
    ["status", "category", "urgency", "tenant_hash"],
)
REQUEST_DURATION_SECONDS = Histogram(
    "gdev_request_duration_seconds",
    "End-to-end request latency",
    ["endpoint", "tenant_hash"],
)
PENDING_TOTAL = Counter(
    "gdev_pending_total",
    "Actions that required human approval",
    ["tenant_hash"],
)
APPROVED_TOTAL = Counter(
    "gdev_approved_total",
    "Actions approved by humans",
    ["tenant_hash"],
)
REJECTED_TOTAL = Counter(
    "gdev_rejected_total",
    "Actions rejected by humans",
    ["tenant_hash"],
)
APPROVAL_QUEUE_DEPTH = Gauge(
    "gdev_approval_queue_depth",
    "Current pending decisions not yet resolved",
    ["tenant_hash"],
)

GUARD_BLOCKS_TOTAL = Counter(
    "gdev_guard_blocks_total",
    "Guard block events",
    ["guard_type", "reason", "tenant_hash"],
)
GUARD_REDACTIONS_TOTAL = Counter(
    "gdev_guard_redactions_total",
    "Guard redactions",
    ["guard_type", "tenant_hash"],
)
INJECTION_ATTEMPTS_TOTAL = Counter(
    "gdev_injection_attempts_total",
    "Input injection pattern hits",
    ["tenant_hash"],
)

LLM_REQUESTS_TOTAL = Counter(
    "gdev_llm_requests_total",
    "LLM API calls",
    ["model", "status", "tenant_hash"],
)
LLM_DURATION_SECONDS = Histogram(
    "gdev_llm_duration_seconds",
    "LLM round-trip time",
    ["model", "tenant_hash"],
)
LLM_TOKENS_TOTAL = Counter(
    "gdev_llm_tokens_total",
    "Token consumption",
    ["direction", "model", "tenant_hash"],
)
LLM_COST_USD_TOTAL = Counter(
    "gdev_llm_cost_usd_total",
    "LLM cost in USD",
    ["model", "tenant_hash"],
)
LLM_TURNS_USED = Histogram(
    "gdev_llm_turns_used",
    "Tool-use turns consumed per request",
    ["tenant_hash"],
)
LLM_RETRY_TOTAL = Counter(
    "gdev_llm_retry_total",
    "LLM retries triggered",
    ["tenant_hash"],
)

BUDGET_UTILIZATION_RATIO = Gauge(
    "gdev_budget_utilization_ratio",
    "Current day cost / daily budget",
    ["tenant_hash"],
)
BUDGET_EXCEEDED_TOTAL = Counter(
    "gdev_budget_exceeded_total",
    "Requests blocked due to budget exhaustion",
    ["tenant_hash"],
)

INTEGRATION_ERRORS_TOTAL = Counter(
    "gdev_integration_errors_total",
    "Integration failure count",
    ["integration", "tenant_hash"],
)
INTEGRATION_DURATION_SECONDS = Histogram(
    "gdev_integration_duration_seconds",
    "Integration call latency",
    ["integration", "tenant_hash"],
)

RCA_CLUSTERS_ACTIVE = Gauge(
    "gdev_rca_clusters_active",
    "Active RCA cluster count by tenant",
    ["tenant_hash"],
)
RCA_RUN_DURATION_SECONDS = Histogram(
    "gdev_rca_run_duration_seconds",
    "RCA run duration per tenant",
    ["tenant_hash"],
)
RCA_TICKETS_SCANNED_TOTAL = Counter(
    "gdev_rca_tickets_scanned",
    "Tickets scanned by RCA runs",
    ["tenant_hash"],
)
EMBEDDING_DURATION_SECONDS = Histogram(
    "gdev_embedding_duration_seconds",
    "Embedding upsert latency in seconds",
    ["tenant_hash"],
)


def render_metrics() -> bytes:
    return generate_latest()
