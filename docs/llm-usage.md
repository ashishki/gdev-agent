# LLM Usage Governance v1.0

_Date: 2026-03-03_
_This document defines how LLM usage is tracked, controlled, and reported across all tenants._

---

## 1. Usage Tracking

### 1.1 What is tracked

Every LLM API call records:

| Field | Source | Storage |
|---|---|---|
| `tenant_id` | JWT context | `audit_log`, `cost_ledger` |
| `request_id` | RequestID middleware | `audit_log` |
| `model_id` | `agent_configs.model_id` | `audit_log` |
| `prompt_version` | `agent_configs.prompt_version` | `audit_log` |
| `input_tokens` | Anthropic API response | `audit_log`, `cost_ledger` |
| `output_tokens` | Anthropic API response | `audit_log`, `cost_ledger` |
| `cost_usd` | Calculated: tokens × per-1k rate | `audit_log`, `cost_ledger` |
| `latency_ms` | `time.monotonic()` delta | `audit_log` |
| `turns_used` | LLM loop counter | `audit_log` |
| `status` | `ok` / `error` / `retry` / `budget_blocked` | `audit_log` |
| `category` | Classification output | `audit_log` |
| `confidence` | Classification output | `audit_log` |
| `agent_config_id` | Active config version | `audit_log` |

**Not tracked:** Prompt text, completion text, raw player message, user PII.

### 1.2 Tracking implementation

Token counts and cost are captured immediately after the Anthropic API response:

```
LLMClient.run_agent()
  → Anthropic API response received
  → extract: usage.input_tokens, usage.output_tokens
  → cost_usd = (input / 1000 × input_rate) + (output / 1000 × output_rate)
  → CostLedger.record(tenant_id, date.today(), input_tokens, output_tokens, cost_usd)
      → Postgres UPSERT cost_ledger (atomic, no double-count)
  → emit structured log event "llm_call_complete"
  → increment Prometheus counters
```

### 1.3 Cost ledger reconciliation

The `CostAggregator` runs hourly:
```sql
INSERT INTO cost_ledger (tenant_id, date, input_tokens, output_tokens, cost_usd, request_count)
SELECT tenant_id,
       DATE(created_at),
       SUM(input_tokens),
       SUM(output_tokens),
       SUM(cost_usd),
       COUNT(*)
FROM audit_log
WHERE DATE(created_at) = CURRENT_DATE
GROUP BY tenant_id, DATE(created_at)
ON CONFLICT (tenant_id, date) DO UPDATE
  SET input_tokens  = EXCLUDED.input_tokens,
      output_tokens = EXCLUDED.output_tokens,
      cost_usd      = EXCLUDED.cost_usd,
      request_count = EXCLUDED.request_count;
```

This reconciles any real-time ledger writes that failed and provides a source of truth for
weekly reports.

---

## 2. Prompt Versioning

### 2.1 Version format

Prompt versions follow the pattern: `{agent_name}-v{major}.{minor}`

Examples:
- `triage-v1.0` — initial triage prompt
- `triage-v1.1` — minor tweak (reworded instruction, no schema change)
- `triage-v2.0` — major change (new tool, new output schema, or new guardrail)

### 2.2 Version lifecycle

1. Prompt changes are committed to `app/prompts/{agent_name}/v{major}.{minor}.txt`.
2. `agent_configs` row updated: `prompt_version`, `version` column bumped.
3. Old row's `is_current = FALSE` (retained for audit trail; old eval runs reference it).
4. Eval run triggered immediately with new config. Must not regress F1 by > 0.02.
5. If regression: revert `is_current`, open PR to fix, do not deploy.

### 2.3 Per-tenant prompt pinning

Tenants may pin to a specific `agent_config_id` to avoid automatic prompt upgrades:
```json
{
  "tenant_id": "uuid",
  "pinned_agent_config_id": "uuid | null"
}
```
`null` = always use `is_current = TRUE` config. Non-null = pinned to that version.

---

## 3. Error Categories

Every LLM call failure is categorized for structured reporting:

| Error Code | Meaning | Typical Cause |
|---|---|---|
| `llm_network_error` | Network failure before response | Connectivity issue |
| `llm_rate_limit` | Anthropic 429 | Throughput exceeds tier |
| `llm_overloaded` | Anthropic 529 | Anthropic capacity issue |
| `llm_context_length` | Input exceeds model context | Prompt too long or input too large |
| `llm_invalid_response` | Response did not match expected tool schema | Model deviation or schema mismatch |
| `llm_max_turns` | Loop exited without tool completion | Model stuck in reasoning |
| `llm_budget_blocked` | Request rejected before API call due to budget | Tenant at 100 % budget |
| `llm_unknown_tool` | Model returned a tool name not in registry | Model hallucinated tool call |

Each error increments `gdev_llm_requests_total{status="error", error_code=...}`.

---

## 4. Hallucination Tracking

### 4.1 Definition (in this system)

A hallucination is any output where the model:
- Returns a tool name not in `TOOL_REGISTRY`.
- Returns a `category` value not in the allowed enum.
- Returns `confidence > 0.9` for a case that an evaluator labeled with a different category.
- Generates a URL not in the allowlist (caught by output guard).
- Generates text that contains a secret pattern (caught by output guard).

### 4.2 Detection

| Type | Detection method | Where logged |
|---|---|---|
| Unknown tool name | `TOOL_REGISTRY.get()` returns None | `audit_log.status = "hallucination"` |
| Invalid category enum | Pydantic validation failure | `audit_log.status = "validation_error"` |
| Confident but wrong | Eval run F1 vs. expected label | `eval_runs.per_category.hallucination_rate` |
| URL/secret in output | Output guard redaction or block | `gdev_guard_blocks_total`, `audit_log` |

### 4.3 Escalation

- Any hallucination that reaches the output guard increments `gdev_guard_blocks_total`.
- If `llm_unknown_tool` rate > 1 % in a 1-hour window: alert `CRITICAL`. Review prompt version.
- If output guard blocks > 0 responses in 5 minutes: alert `CRITICAL`. Possible prompt injection
  or model degradation.

---

## 5. Human Override Tracking

Every HITL decision is recorded as an `approval_events` row. The override rate measures how
often humans disagree with the agent's proposed action.

### 5.1 Override definition

| Event | Override? | Notes |
|---|---|---|
| Approved (risky=True action) | No | Human confirms agent's caution |
| Rejected (risky=True action) | **Yes** | Human disagrees with proposed action |
| Approved but modified payload | **Yes** | Partial override (not yet implemented; tracked as rejected + manual action) |
| Expired without review | Ambiguous | Tracked separately as `expired_pending` |

### 5.2 Metrics

```sql
-- Weekly override rate per tenant
SELECT
  tenant_id,
  COUNT(*) FILTER (WHERE decision = 'rejected') AS overrides,
  COUNT(*) AS total_approvals,
  ROUND(100.0 * COUNT(*) FILTER (WHERE decision = 'rejected') / COUNT(*), 1) AS override_pct
FROM approval_events
WHERE created_at >= NOW() - INTERVAL '7 days'
GROUP BY tenant_id;
```

### 5.3 Override analysis

If override rate > 20 % for a tenant over 2 consecutive weeks:
1. Review `risk_reason` distribution for rejected actions.
2. Consider adjusting `auto_approve_threshold` (lower to increase HITL rate) or
   `approval_categories` (add/remove categories).
3. Open a prompt review PR if the model is flagging the wrong cases as risky.

---

## 6. Weekly Reporting Format

The weekly LLM usage report is generated every Monday and stored as a JSON file in
`reports/{YYYY-WW}.json` and optionally emailed to tenant admins.

### Report Schema

```json
{
  "report_period": "2026-W09",
  "generated_at": "2026-03-02T00:00:00Z",
  "tenants": [
    {
      "tenant_id_hash": "...",
      "tenant_slug": "acme-games",
      "requests_total": 1240,
      "requests_auto_executed": 1100,
      "requests_pending": 140,
      "requests_approved": 125,
      "requests_rejected": 15,
      "override_rate_pct": 10.7,
      "llm_calls_total": 1240,
      "llm_errors_total": 8,
      "llm_retry_total": 23,
      "input_tokens_total": 512000,
      "output_tokens_total": 108000,
      "cost_usd_total": 3.18,
      "cost_per_request_avg_usd": 0.00257,
      "budget_usd": 10.00,
      "budget_utilization_pct": 31.8,
      "classification_accuracy_f1": 0.89,
      "guard_blocks_input": 4,
      "guard_blocks_output": 0,
      "hallucination_count": 1,
      "rca_clusters_generated": 7,
      "top_categories": {
        "bug_report": 430,
        "billing": 280,
        "account_access": 215,
        "gameplay_question": 180,
        "cheater_report": 95,
        "other": 40
      },
      "prompt_version": "triage-v1.1",
      "model_id": "claude-sonnet-4-6",
      "eval_run_f1": 0.89,
      "eval_regression_alert": false
    }
  ],
  "platform_totals": {
    "requests_total": 12400,
    "cost_usd_total": 31.8,
    "llm_errors_total": 80
  }
}
```

### Report generation

```bash
# Triggered by CostAggregator on Monday 00:00 UTC
python -m app.jobs.weekly_report --week 2026-W09
```

Report is also accessible via `GET /metrics/report?week=2026-W09` (tenant-scoped; platform
totals only for `tenant_admin` of a special `platform` tenant).
