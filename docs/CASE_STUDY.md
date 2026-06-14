# gdev-agent Case Study

## Problem

Game-studio support teams receive billing disputes, account-access incidents,
bug reports, moderation signals, and repetitive gameplay questions through
webhooks and workflow tools. The hard part is not just classification; it is
keeping risky actions behind review, preserving tenant isolation, and leaving a
usable audit trail.

`gdev-agent` is a local/pilot portfolio implementation of that workflow. The
problem is bounded to support triage reliability; this is not an external
deployment or production SaaS claim.

## Architecture

The architecture is HTTP-first:

1. A signed tenant webhook enters `POST /webhook`.
2. Middleware verifies tenant slug/HMAC, rate limits, and request correlation.
3. Guardrails block oversized or injection-shaped input before model use.
4. The LLM tool loop classifies, extracts, and drafts a response.
5. Policy and output guard decide whether execution is safe or needs review.
6. Risky work is stored as a Redis pending approval and resolved through
   `POST /approve`.
7. Execution writes ticket, audit, metrics, and cost evidence.

Primary proof: [docs/ARCHITECTURE.md](ARCHITECTURE.md),
[docs/architecture-diagram.md](architecture-diagram.md),
[docs/data-map.md](data-map.md), and [README.md](../README.md).

## Control Boundaries

The project focuses on controls that are inspectable in a local repo:

- Tenant isolation: PostgreSQL RLS, tenant-scoped JWTs, per-tenant webhook HMAC,
  tenant-keyed Redis state, and tenant-scoped cost ledger tests.
- Approval safety: low-confidence or high-risk actions require review; approval
  decisions are tenant-bound and role-protected.
- Output safety: secret scanning, URL allowlist enforcement, and structured
  output validation run before responses leave the service boundary.
- Operational evidence: JSON logs, Prometheus metrics, OpenTelemetry-style
  spans, Grafana/Loki/Tempo local stack, migration checks, and health notes.

Proof starts at [docs/architecture-diagram.md](architecture-diagram.md),
[docs/TENANT_ISOLATION.md](TENANT_ISOLATION.md),
[docs/FAILURE_MODES.md](FAILURE_MODES.md), and
[docs/observability.md](observability.md).

## Failure Modes

The committed failure modes cover duplicate webhook replay, Redis and
Postgres outages, LLM timeout/malformed output, approval expiry, budget
exhaustion, guardrail blocks, and cross-tenant access attempts. The runbook
keeps these as local operating targets, not production incident evidence.

Proof: [docs/FAILURE_MODES.md](FAILURE_MODES.md) and
[docs/SLO_RUNBOOK.md](SLO_RUNBOOK.md).

## Eval Results

The current eval corpus has 180 synthetic cases. The deterministic demo-mode
baseline is useful as a regression signal, not as live model quality evidence.

Latest committed eval results from [docs/EVAL_REPORT.md](EVAL_REPORT.md):

| Metric | Value | Interpretation |
| --- | ---: | --- |
| Guard block rate | 1.0000 | Known injection cases are blocked. |
| Risk routing recall | 0.4259 | Passes current smoke threshold. |
| Unsafe auto-approval rate | 0.5741 | Passes current smoke threshold; quality work remains. |
| Invalid structured output rate | 0.0000 | Structured output contract holds in demo mode. |
| Classification accuracy | 0.2222 | Observed only; demo classifier does not claim broad taxonomy quality. |

The CI eval regression gate is active for smoke regressions. Stricter quality
gates remain future work.

## Load Results

The load evidence is deterministic/local. It proves the harness, scenario
fixtures, and KPI checker, not production capacity.

Committed load results from [docs/LOAD_TEST_REPORT.md](LOAD_TEST_REPORT.md):

| Scenario | p95 | Error rate | Signal |
| --- | ---: | ---: | --- |
| `low_load` | 480 ms | 0.00% | Compose-safe smoke load. |
| `mixed_10_tenant` | 720 ms | 0.00% | Multi-tenant synthetic traffic shape. |
| `duplicate_replay` | 160 ms | 0.00% | Dedup path with 96% dedup hit rate. |
| `risky_action_heavy` | 650 ms | 0.00% | Approval-heavy flow with 71% approval creation. |
| `provider_latency` | 1220 ms | 0.00% | Simulated provider-latency profile. |

## Trade-Offs

- The implementation favors explicit service boundaries and local proof over UI
  breadth. There is no chat UI or open-ended agent behavior.
- Demo mode keeps review free and deterministic, but live LLM quality is not
  proven by the committed baseline.
- Redis stores ephemeral coordination state; Postgres is the durable source of
  record.
- Read APIs still have known service-extraction debt for ticket, analytics, and
  cluster reads.

## What Would Change For Production

Before production readiness, this would need external deployment evidence,
managed secrets, TLS/network controls, Redis ACL and persistence decisions,
managed database backups with restore drills, measured live load, production
observability operations, stricter eval gates, and real tenant/user evidence.

Those limits are documented in
[docs/DEPLOYMENT_READINESS.md](DEPLOYMENT_READINESS.md) and
[README.md#known-limits](../README.md#known-limits).
