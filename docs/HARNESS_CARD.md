# gdev-agent Harness Card

Status: bounded support-triage harness for local/pilot evidence.

This card defines the agent as a full harness, not as a standalone model. Review
quality must compare model + prompt/tool loop + guards + approvals + trace +
eval behavior together.
The review phrase is explicit: model + prompt/tool loop + guards + approvals + trace + eval are one system boundary.

## Harness Boundary

| Area | Current Contract |
| --- | --- |
| Entry point | `POST /webhook` through FastAPI and middleware |
| Orchestrator | n8n owns outer workflow retries, approval UI, and operator alerts |
| Agent loop | `app/agent.py` calls `app/llm_client.py` for classification, extraction, draft, FAQ lookup, and human flagging |
| Model mode | Deterministic demo mode by default; live Anthropic mode only with explicit key and budget controls |
| Tools | Ticket creation, reply sending, FAQ lookup, approval notification, audit export |
| Memory | No autonomous long-term memory; uses request context, tenant config, pending approvals, dedup cache, audit rows, eval exemplars |
| Writes | Low-risk tool execution only; risky or low-confidence actions go pending |
| Human handoff | `POST /approve`, Telegram/n8n approval workflow, reviewer identity, decision notes |
| Termination | One webhook produces executed, pending, rejected, guarded, duplicate, or error outcome |

## Prompt And Model Boundary

- Prompt/tool schema changes are harness changes.
- Live model changes must record provider, model name, prompt/tool version,
  eval dataset, threshold result, cost estimate, and rollback plan.
- Deterministic demo behavior is valid for mechanics proof only; it is not live
  model quality proof.

## Tool Registry

| Tool Surface | Permission Class | Required Guard |
| --- | --- | --- |
| Ticket creation | Write | Tenant context, dedup, risk policy, output guard |
| Reply sending | Customer-facing write | URL allowlist, secret scan, confidence floor, approval when risky |
| FAQ lookup | Read | Tenant-safe source boundary |
| Pending approval store | State write | Tenant ID, TTL, reviewer callback HMAC |
| Audit/log/metrics | Observability write | Redaction and tenant-safe labels |

## Retry And Recovery

- App-level agent loop is bounded and must not spin indefinitely.
- n8n owns external retries and operator alerts.
- Duplicate webhooks use message-id idempotency.
- Redis/Postgres/provider failures must degrade to explicit error, pending
  review, or manual fallback, not silent auto-execution.

## Permissions

| Allowed | Ask First | Blocked |
| --- | --- | --- |
| Classify, extract, summarize, draft, create low-risk ticket | Live provider calls, customer-facing replies, policy-sensitive changes | Refunds, account access restoration, legal/GDPR final decisions, cross-tenant access |

## Trace Requirements

Every reviewed run should be reconstructable from:

- request ID and tenant ID/hash;
- message ID and dedup status;
- input guard result;
- model/provider/prompt/tool version;
- tool calls and observations;
- policy decision, risk flag, confidence, and risk reason;
- output guard decision and redaction events;
- approval decision, reviewer, latency, and correction markers;
- cost, token estimates when available, and latency;
- final route and action result.

See `docs/TRACE_SCHEMA.md` for the JSONL contract.

## Eval Requirements

Required before making harness behavior more autonomous:

- `eval/cases.jsonl` gate passes in deterministic mode;
- `eval/harness_regression.jsonl` scenarios are represented in tests or a
  runner adapter;
- risk routing recall, unsafe auto-approval rate, guard block rate, invalid
  structured output rate, cost, and latency remain within thresholds;
- human approval and tenant-isolation tests pass;
- trace completeness is reviewed for changed paths.

## Known Non-Goals

- No autonomous code or prompt self-modification.
- No production deployment claim from demo fixtures.
- No live delegated payments, refunds, account restoration, legal advice, or
  cross-tenant data access.
- No memory layer that stores free-form user content outside documented stores.
