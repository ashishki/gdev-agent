# Resume Bullets

These bullets are copy-ready starting points for a resume, LinkedIn profile, or
portfolio summary. Keep the evidence links nearby when using them; the numbers
come from local/synthetic repo proof and are not production-user claims.

## Copy-Ready Bullets

- Built a multi-tenant FastAPI support-triage backend for game-studio workflows,
  covering signed webhooks, input/output guardrails, an LLM tool loop, human
  approval, audit history, and tenant-scoped cost tracking; current repo
  baseline is 285 passing unit/integration tests
  ([README](../README.md#current-status), [architecture](ARCHITECTURE.md)).
- Implemented tenant isolation across Postgres RLS, tenant-scoped JWT/RBAC,
  per-tenant webhook HMAC, tenant-keyed Redis state, approval boundaries, and
  cost ledger separation, with dedicated isolation/security tests
  ([tenant isolation proof](TENANT_ISOLATION.md)).
- Added a deterministic eval harness over 180 synthetic support cases, including
  prompt-injection, unsafe URL/output, duplicate webhook, budget, and
  tenant-boundary cases; current smoke baseline blocks all known injection cases
  and has 0.0000 invalid structured-output rate
  ([eval report](EVAL_REPORT.md)).
- Built a local deterministic load harness with five review scenarios covering
  low load, 10-tenant traffic shape, duplicate replay, approval-heavy traffic,
  and provider-latency simulation; committed fixture shows 0.00% error rate and
  p95 latency from 160 ms to 1220 ms across scenarios
  ([load report](LOAD_TEST_REPORT.md)).
- Instrumented observability with Prometheus metrics, OpenTelemetry-style spans,
  structured JSON logs, and a local Grafana/Loki/Tempo dashboard for request,
  guardrail, approval, budget, LLM, and integration signals
  ([observability](observability.md)).

## Short Portfolio Summary

`gdev-agent` is a local/pilot portfolio implementation of a governed AI support
pipeline: signed webhook ingress, guardrails, LLM-assisted triage, human
approval for risky work, audited execution, tenant isolation, eval regression
signals, deterministic load evidence, and local observability.

## Claims To Avoid

- Do not claim production SaaS readiness, production-user traffic, external
  customer adoption, production load capacity, or live model quality.
- Do not present the eval baseline as broad model accuracy; it is a deterministic
  smoke-regression signal over synthetic cases.
- Do not present the load results as infrastructure capacity; they are local
  deterministic/synthetic fixtures and harness proof.

## Evidence Map

| Topic | Evidence |
| --- | --- |
| tests | [README current status](../README.md#current-status) |
| eval | [docs/EVAL_REPORT.md](EVAL_REPORT.md) |
| load | [docs/LOAD_TEST_REPORT.md](LOAD_TEST_REPORT.md) |
| tenant isolation | [docs/TENANT_ISOLATION.md](TENANT_ISOLATION.md) |
| observability | [docs/observability.md](observability.md) |
| production-user limits | [README known limits](../README.md#known-limits) |
