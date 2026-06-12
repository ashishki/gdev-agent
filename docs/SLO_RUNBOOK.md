# Local SLO And Runbook Notes

This runbook defines local portfolio targets for the demo and test harness. It is not a production
SLA, pager contract, or customer-facing availability claim.

## Scope

- Applies to local Compose, deterministic demo mode, and future load-test evidence.
- Uses tenant-safe observability only: tenant IDs in metrics, logs, and traces must be hashed.
- References the canonical failure taxonomy in [FAILURE_MODES.md](FAILURE_MODES.md).
- Treats HTTP 429 rate-limit and budget responses as expected control behavior, not 5xx errors.

## Local Targets

| Area | Local target | Measurement | Runbook trigger |
|------|--------------|-------------|-----------------|
| Webhook latency | p50 < 2 s and p99 < 8 s for LLM-bound burst traffic; p99 < 5 s during steady traffic. | `gdev_request_duration_seconds`, Locust Scenario A/B, trace duration. | p99 exceeds target for two consecutive local runs or any single run exceeds 15 s. |
| API error rate | HTTP 5xx < 1% in steady local scenario; 429 excluded from error rate. | Request logs, `gdev_requests_total`, CI/load report. | HTTP 5xx > 2% or repeated 5xx from one dependency path. |
| Approval queue behavior | Pending approvals are visible, TTL-bound, and do not grow without explanation; local warning threshold is queue depth > 20 per tenant. | `gdev_approval_queue_depth`, pending decision logs, Redis TTL inspection. | Queue depth > 20, expired approvals spike, or approval notification failures repeat. |
| Guard blocks | Output guard block count should be zero in normal demo traffic; any output block is safety-critical evidence to inspect. | `gdev_guard_blocks_total`, `agent.output_guard` spans, eval unsafe-output cases. | Any `FM_OUTPUT_GUARD_BLOCK` in demo or CI eval paths. |
| Dependency failure response | Redis correctness paths fail closed, rate limit Redis failure fails open with `rate_limit_bypass`, Postgres/LLM failures do not unsafe auto-execute. | Failure-mode tests, service logs, traces, dependency health checks. | Any dependency failure creates duplicate side effects, cross-tenant access, or unsafe auto-execution. |
| Budget control | Budget check runs before LLM calls and blocks at `daily_budget_usd`. | `gdev_budget_utilization_ratio`, `gdev_budget_exceeded_total`, cost ledger tests. | Budget exceeded without 429, or LLM called after `FM_BUDGET_EXCEEDED`. |

## Runbook Index

| Failure mode | First check | Immediate response | Follow-up proof |
|--------------|-------------|--------------------|-----------------|
| `FM_DUPLICATE_WEBHOOK_REPLAY` | Check `dedup_hit` / `webhook_dedup_hit` logs for the tenant hash and message ID path. | Confirm the replay returned the cached HTTP 200 response; do not manually recreate tickets or approvals. | Run `pytest tests/test_dedup.py -q`; after T12, run the webhook replay workflow test. |
| `FM_REDIS_UNAVAILABLE` | Check startup logs or runtime exceptions around dedup/approval store calls. | Restore Redis before replaying correctness-critical requests. Treat failed approvals/dedup as not safely completed. | After T13, run Redis degradation tests; inspect Redis key namespace health. |
| `FM_REDIS_DEGRADED_RATE_LIMIT` | Look for `rate_limit_bypass` and traffic spikes. | Keep serving requests, but watch abuse indicators and consider upstream throttling. | Run middleware rate-limit tests and review request metrics. |
| `FM_POSTGRES_UNAVAILABLE` | Check service error logs, DB connection health, and failed request traces. | Restore Postgres, then compare audit/ticket/pending rows before replay. | After T13, run Postgres dependency tests. |
| `FM_POSTGRES_DEGRADED` | Inspect p99 latency, DB connection count, locks, and slow queries. | Reduce background RCA load and replay only terminal failed requests. | Use `docs/load-profile.md` scenarios to confirm recovery. |
| `FM_LLM_TIMEOUT` | Check `llm.api_call` spans, `gdev_llm_requests_total{status="error"}`, and retry counts. | Verify no action executed without valid classification; retry through upstream only if safe. | Run LLM client/provider degradation tests after T13. |
| `FM_LLM_MALFORMED_OUTPUT` | Search for `llm_invalid_response` and eval `invalid_structured_output_rate`. | Keep fail-closed behavior; do not relax validators without adding eval cases. | Run `pytest tests/test_eval_runner.py tests/test_eval_service.py -q`. |
| `FM_OUTPUT_GUARD_BLOCK` | Check output guard block metric and span attributes. | Treat as safety-critical; preserve sample metadata without raw prompt/response text. | Run output guard tests after T12 and eval unsafe-output cases. |
| `FM_APPROVAL_TTL_EXPIRED` | Check `pending_expired` and approval queue age. | Tell reviewer the approval expired; create a fresh pending action if still needed. | Run `pytest tests/test_redis_approval_store.py -q`; full flow after T12/T14. |
| `FM_CROSS_TENANT_APPROVAL` | Compare hashed JWT tenant context with pending decision tenant ownership. | Reject as a security event; do not retry with mismatched tenant credentials. | Run T14 cross-tenant approval boundary tests when implemented. |
| `FM_RATE_LIMIT_EXCEEDED` | Inspect 429 rate, tenant/user distribution, and `rate_limit.blocked=true` spans. | Honor retry delay; tune only if normal demo traffic is blocked. | Run middleware tests and load Scenario A. |
| `FM_BUDGET_EXCEEDED` | Check budget utilization, `gdev_budget_exceeded_total`, and cost ledger rows. | Do not retry until reset or approved budget change; verify no LLM call happened after block. | Run `pytest tests/test_cost_ledger.py tests/test_eval.py tests/test_eval_runner.py -q` where environment allows. |

## Escalation Rules

- Safety or tenant isolation failures (`FM_OUTPUT_GUARD_BLOCK`, `FM_CROSS_TENANT_APPROVAL`) are
  security-critical for review purposes and require deep review before closure.
- Dependency failures are acceptable only when the documented behavior preserves correctness:
  idempotency, tenant isolation, approval audit, and no unsafe auto-execution.
- Documentation should not change a local target into a production SLA unless an external
  deployment, monitoring path, and on-call ownership exist.

## Evidence Commands

```bash
rg -n "FM_DUPLICATE_WEBHOOK_REPLAY|FM_BUDGET_EXCEEDED|SLO|runbook" docs/FAILURE_MODES.md docs/SLO_RUNBOOK.md
pytest tests/test_dedup.py tests/test_redis_approval_store.py tests/test_cost_ledger.py -q
pytest tests/test_eval_runner.py tests/test_eval_service.py -q
```

Some integration tests require Docker or an external test database. If those dependencies are not
available, record the skip reason and rely on the documented local smoke commands for the current
portfolio proof.

