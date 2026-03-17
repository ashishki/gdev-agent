# Agent Registry v2.0

_Date: 2026-03-17_
_Merged from AGENT_SYSTEM.md (pipeline design) + agent-registry.md (agent profiles)._
_Single source of truth for the AI pipeline. Each agent corresponds to an `agent_configs` row in Postgres. Config changes require a version bump and a PR._

---

## Pipeline Architecture

```
POST /webhook
     │
     ▼
[Input Guard]
  15 injection patterns + length check
  Raises ValueError → HTTP 400 (before any LLM call)
     │
     ▼
[Budget Check]
  CostLedger.check_budget(tenant_id)
  Raises BudgetExhaustedError → HTTP 429
     │
     ▼
[LLMClient.run_agent()]  ← Claude tool_use loop (≤5 turns)
  │
  ├── Turn 1: classify_request → ClassificationResult
  ├── Turn 1: extract_entities → ExtractedFields
  ├── Turn N: lookup_faq (optional) → KB articles
  ├── Turn N: draft_reply (optional) → draft_text
  └── Turn N: flag_for_human (optional) → force_pending=True
     │
     ▼
[Output Guard]
  Secret scan + URL allowlist + confidence floor
  Blocked → HTTP 500 (internal)
  Redacted → log + continue with cleaned draft
     │
     ▼
[propose_action()]
  Builds ProposedAction with risky: bool + risk_reason
  Risk conditions: category, urgency, confidence, legal keywords
     │
     ▼
[Route Decision]
  risky=True  → pending (RedisApprovalStore)
  risky=False → execute (TOOL_REGISTRY)
```

---

## LLM Tool Definitions

### `classify_request`

```json
{
  "category": "bug_report | billing | account_access | cheater_report | gameplay_question | other",
  "urgency": "low | medium | high | critical",
  "confidence": 0.0–1.0
}
```

`confidence < AUTO_APPROVE_THRESHOLD (0.85)` sets `risky=True`. Fallback: `{category: "other", urgency: "low", confidence: 0.0}`.

### `extract_entities`

```json
{
  "user_id": "string | null",
  "platform": "iOS | Android | PC | PS5 | Xbox | unknown",
  "game_title": "string | null",
  "transaction_id": "string | null",
  "error_code": "string | null",
  "reported_username": "string | null",
  "keywords": ["string"]
}
```

### `lookup_faq`

Returns top-3 KB articles by keyword. URLs subject to output guard allowlist.

### `draft_reply`

```json
{
  "tone": "empathetic | informational | escalation",
  "include_faq_links": true,
  "draft_text": "string"
}
```

`draft_text` passes through output guard before reaching the user.

### `flag_for_human`

```json
{
  "reason": "string",
  "risk_level": "medium | high | critical"
}
```

Sets `force_pending=True` → overrides confidence to `0.0` → `propose_action()` marks `risky=True`.

---

## System Prompt

```
You are a game support triage assistant.
Use available tools to classify requests and extract entities.
Always call classify_request and extract_entities before ending your turn.
```

Minimal prompt forcing two mandatory tool calls. `tool_choice: auto` — model decides when to use optional tools.

---

## Tool-Use Loop

```python
for turn in range(max_turns=5):
    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=700,
        tools=TOOLS,
        tool_choice={"type": "auto"},
        messages=messages,
    )
```

Max turns: 5. Max tokens: 700. In practice 1–2 turns typical.

---

## Guardrails

### Input Guard (`AgentService._guard_input`)

Runs before any LLM call. Blocks text > `MAX_INPUT_LENGTH` (2000) or matching 15 injection patterns:
`"ignore previous instructions"`, `"system:"`, `"[inst]"`, `"act as if you"`, `"you are now"`, `"forget all"`, `"disregard"`, `"developer mode"`, `"jailbreak"`, `"bypass"`, `"pretend you"`, `"<|system|>"`, `"[system]"`, `"###instruction"`.

On block: raises `ValueError` → HTTP 400. Increments `INJECTION_ATTEMPTS_TOTAL`.

### Output Guard (`app/guardrails/output_guard.py`)

Runs after LLM loop, before routing:
1. **Secret scan** — regex for API keys, tokens, credentials
2. **URL allowlist** — strips/rejects URLs not in `settings.url_allowlist`
3. **Confidence floor** — `confidence < threshold` → override action to pending

### Confidence Thresholds

| Threshold | Config var | Default | Effect |
|---|---|---|---|
| Auto-approve | `AUTO_APPROVE_THRESHOLD` | 0.85 | Below → `risky=True` |
| Confidence floor | output guard internal | 0.5 | Below → may block |

---

## Human-in-the-Loop Pattern

Risk conditions (any one triggers pending):
- `category in APPROVAL_CATEGORIES` (default: `["billing", "account_access"]`)
- `urgency in {"high", "critical"}`
- `confidence < AUTO_APPROVE_THRESHOLD`
- text contains legal keywords: `"lawyer"`, `"lawsuit"`, `"press"`, `"gdpr"`
- `flag_for_human` called

Pending flow: `propose_action() → risky=True → Redis store (TTL: 3600s) → Telegram notify → POST /approve → execute/reject → approval_events`.

`RedisApprovalStore.pop_pending()` uses `GETDEL` — atomic, one-time consumption.

---

## Token Budget and Cost Control

```python
cost_usd = (input_tokens / 1000) * llm_input_rate_per_1k
         + (output_tokens / 1000) * llm_output_rate_per_1k
```

- `CostLedger.check_budget(tenant_id)` — raises `BudgetExhaustedError` if spend ≥ `daily_budget_usd`
- `CostLedger.record(...)` — UPSERT to `cost_ledger` after each request
- `BUDGET_UTILIZATION_RATIO` Prometheus gauge updated after each record

RCA summarization cost tracked separately (`rca_budget_per_run_usd`, default $0.15/run).

---

## Tool Registry (post-LLM execution)

```python
TOOL_REGISTRY = {
    "create_ticket_and_reply": _create_ticket_and_reply,
}
```

**Adding new tools:**
1. Add tool schema to `TOOLS` in `app/llm_client.py`
2. Add dispatch case in `LLMClient._dispatch_tool()`
3. Add handler in `app/tools/` and register in `TOOL_REGISTRY`
4. Update this file (`docs/agent-registry.md`)

---

## Registry Overview

| Agent Name | Purpose | Trigger | Role Sensitivity |
|---|---|---|---|
| `TriageAgent` | Classify, extract, propose action for a player support ticket | Every webhook | Low (output is category/urgency, no PII) |
| `ApprovalAgent` | Execute a previously proposed action after human approval | `POST /approve` | Medium (executes actions on behalf of reviewer) |
| `RCAClustererAgent` | Cluster recent tickets by semantic similarity; summarize root causes | Background (15 min) | Low (reads embeddings, outputs cluster labels) |
| `GuardAgent` | Input and output scanning (injection, secrets, URLs) | Every pipeline run | High (gate between raw input and LLM) |
| `EvalAgent` | Run evaluation harness against `eval/cases.jsonl` | On-demand or daily | Low (read-only; synthetic cases only) |

---

## 1. TriageAgent

### Purpose
Core pipeline agent. Processes a raw player support message through a Claude `tool_use` loop to
produce a classification, structured field extraction, and a user-facing draft reply. Determines
whether the proposed action is risky and requires human approval.

### Inputs

```json
{
  "tenant_id": "uuid",
  "user_id_hash": "string (SHA-256)",
  "text": "string (validated, ≤ max_input_length)",
  "metadata": {
    "chat_id": "string | null",
    "platform": "string | null",
    "game_title": "string | null"
  }
}
```

### Outputs

```json
{
  "classification": {
    "category": "bug_report | billing | account_access | cheater_report | gameplay_question | other",
    "urgency": "low | medium | high | critical",
    "confidence": 0.0
  },
  "extracted": {
    "transaction_id": "string | null",
    "error_code": "string | null",
    "platform": "string",
    "game_title": "string | null",
    "reported_username": "string | null",
    "keywords": ["string"]
  },
  "draft_response": "string",
  "proposed_action": {
    "tool": "create_ticket_and_reply",
    "payload": {},
    "risky": false,
    "risk_reason": "string | null"
  },
  "token_usage": {
    "input_tokens": 0,
    "output_tokens": 0,
    "cost_usd": 0.0
  }
}
```

### Allowed Tools

| Tool | Purpose | Can mutate state? |
|---|---|---|
| `classify_ticket` | Returns category, urgency, confidence | No |
| `extract_fields` | Returns structured entities from text | No |
| `lookup_faq` | Fetches KB article to inform draft | No (read-only HTTP GET) |
| `create_ticket_and_reply` | Creates ticket + sends reply | Yes — only post-approval or if risky=False |
| `escalate_to_human` | Forces pending state | No (signals, does not execute) |

**Tool execution order is deterministic**: classify → extract → (optionally) lookup_faq →
propose (create_ticket_and_reply or escalate_to_human). The loop exits after the first
mutating tool call or after 5 turns, whichever comes first.

### Failure Modes

| Failure | Behavior |
|---|---|
| Anthropic API error (network, 5xx) | Retry 3x with exponential backoff; return 503 if all fail |
| Confidence < threshold after all turns | Force `risky=True`; route to pending |
| Tool-use loop exceeds 5 turns | Truncate; use last partial result; set `confidence=0.0`; force pending |
| LLM returns unexpected tool name | Log warning; fall back to `escalate_to_human` |
| Output guard blocks draft | Return 500 to caller; do not create ticket |
| Budget exhausted for tenant | Return 429 (budget, not rate limit); no LLM call made |

### Guardrails Applied

1. **InputGuard** (pre-LLM): injection patterns, length, PII pre-scan.
2. **BudgetGuard** (pre-LLM): token budget check against `cost_ledger`.
3. **OutputGuard** (post-LLM): secret scan, URL allowlist, confidence floor.
4. **RiskScorer** (post-LLM): category rules, keyword scan, confidence threshold.

### Role Sensitivity

Output contains no raw PII. Category and urgency labels are low-sensitivity. Draft response
may reference player-provided context — output guard ensures no secrets or disallowed URLs
appear. Any tenant role may read the response; `raw_text` access requires `support_agent+`.

### Agent Config Fields

```json
{
  "agent_name": "TriageAgent",
  "model_id": "claude-sonnet-4-6",
  "max_turns": 5,
  "tools_enabled": ["classify_ticket", "extract_fields", "lookup_faq",
                    "create_ticket_and_reply", "escalate_to_human"],
  "guardrails": {
    "max_input_length": 2000,
    "auto_approve_threshold": 0.85,
    "confidence_floor": 0.5,
    "approval_categories": ["billing"],
    "output_url_behavior": "strip"
  },
  "prompt_version": "triage-v1.0"
}
```

---

## 2. ApprovalAgent

### Purpose
Executes a `ProposedAction` that was previously gated by HITL. Runs after a human reviewer
calls `POST /approve`. Retrieves the pending decision from the approval store, verifies it
has not expired, and invokes the appropriate tool.

### Inputs

```json
{
  "pending_id": "string",
  "approved": true,
  "reviewer": "string (email_hash of reviewer)",
  "tenant_id": "uuid"
}
```

### Outputs

```json
{
  "status": "approved | rejected",
  "pending_id": "string",
  "result": {
    "ticket": {"ticket_id": "uuid"},
    "reply_sent": true
  }
}
```

### Allowed Tools

Same tool registry as TriageAgent, but invoked directly (no LLM turn involved). The action
to execute is fully determined by the stored `ProposedAction`; no new LLM call is made.

### Failure Modes

| Failure | Behavior |
|---|---|
| `pending_id` not found or expired | HTTP 404; log event `pending_expired` |
| Tool execution failure | Return 500; log with `exc_info`; approval event recorded as `failed` |
| Double-approve race | Redis GETDEL atomicity prevents second execution; second call returns 404 |
| Reviewer identity missing | Allowed (anonymous approval); stored as `approved_by=null` in audit |

### Guardrails Applied

- No LLM output guard (no LLM call).
- `APPROVE_SECRET` HMAC verification on request (existing middleware).
- Role check: `support_agent` or `tenant_admin` required.
- `pending_id` scope check: `pending.tenant_id` must match JWT `tenant_id`.

### Role Sensitivity

High: this agent executes real actions (ticket creation, replies). Access restricted to
`support_agent` and `tenant_admin` roles. All executions are recorded in `approval_events`
with reviewer identity (hashed).

---

## 3. RCAClustererAgent

### Purpose
Background agent. Runs on a 15-minute schedule per active tenant. Queries recent ticket
embeddings from pgvector, clusters them using approximate nearest neighbor + DBSCAN, and
generates a short LLM summary for each cluster. Outputs are written to `cluster_summaries`.

### Inputs

```json
{
  "tenant_id": "uuid",
  "lookback_hours": 24,
  "min_cluster_size": 3,
  "similarity_threshold": 0.85
}
```

### Outputs

```json
{
  "clusters": [
    {
      "cluster_id": "uuid",
      "label": "Payment gateway timeout errors",
      "summary": "17 tickets over 6 hours report payment failures at checkout...",
      "ticket_count": 17,
      "severity": "high",
      "first_seen": "ISO-8601",
      "last_seen": "ISO-8601"
    }
  ],
  "run_duration_ms": 0,
  "tickets_scanned": 0
}
```

### Allowed Tools

- pgvector `SELECT ... ORDER BY embedding <=> $1 LIMIT 200` (read-only DB access).
- `LLMClient.summarize_cluster(ticket_texts)` — single Claude call per cluster, no tool_use loop.
- `cluster_summaries` UPSERT (DB write, scoped to tenant).
- Telegram notification (optional, on new/changed clusters).

### Failure Modes

| Failure | Behavior |
|---|---|
| No tickets in window | Skip run; log `rca_no_tickets` |
| LLM summarize call fails | Use generic label "Unknown cluster"; store with `severity=null` |
| Postgres unavailable | APScheduler logs exception; reschedules; no data loss |
| Cluster count explodes (> 50) | Cap at 50; log `rca_cluster_cap_hit`; alert tenant_admin |

### Guardrails Applied

- No output guard (output is internal; never sent to player).
- LLM call uses a simple summarize prompt, not the tool_use loop.
- Cluster labels are reviewed by tenant_admin; no auto-action taken.

### Role Sensitivity

Low. Operates on aggregated, pseudonymized data (embeddings). Cluster summaries contain no
raw PII. Output is visible to `tenant_admin` and `support_agent`.

---

## 4. GuardAgent

### Purpose
Not a standalone LLM-based agent. A deterministic pipeline component that enforces input and
output safety constraints. Treated as an agent for registry purposes because it has versioned
configuration and must be testable in isolation.

### Input Guard

```python
# Checks (in order):
1. len(text) > max_input_length    → ValueError("Input exceeds max length")
2. injection pattern match          → ValueError("Input failed injection guard")
3. (future) PII pre-scan           → strip or reject based on config
```

### Output Guard

```python
# Checks (in order):
1. secret_pattern_scan(draft)       → redact or block
2. url_allowlist_check(draft)       → strip or reject
3. confidence < confidence_floor    → override action to escalate_to_human
```

### Configuration

```json
{
  "agent_name": "GuardAgent",
  "version": 1,
  "guardrails": {
    "injection_patterns": ["ignore previous instructions", "system:", ...],
    "secret_patterns": ["sk-[A-Za-z0-9]{48}", "AKIA[0-9A-Z]{16}", ...],
    "url_allowlist": ["kb.example.com"],
    "output_url_behavior": "strip",
    "max_input_length": 2000,
    "confidence_floor": 0.5
  }
}
```

### Failure Modes

| Failure | Behavior |
|---|---|
| Injection detected | ValueError → HTTP 422 to caller; no LLM call |
| Secret detected in output | Redact token; log `output_guard_redacted` |
| URL not in allowlist | Strip URL or return 500 depending on `output_url_behavior` |
| Confidence below floor | Override `proposed_action.risky=True` |

### Role Sensitivity

High. This is the primary security boundary. Changes to guard patterns require:
1. PR review by at least one other engineer.
2. All adversarial eval cases must still pass (block rate = 1.0).
3. Version bump in `agent_configs`.

---

## 5. EvalAgent

### Purpose
Runs the evaluation harness (`eval/runner.py`) against the current `TriageAgent` configuration.
Produces an `EvalRun` record with per-category F1, guard block rate, mean confidence, and
mean cost. Used for regression detection before and after prompt/config changes.

### Inputs

```json
{
  "tenant_id": "uuid",
  "eval_dataset": "eval/cases.jsonl",
  "agent_config_id": "uuid | null (null = current)"
}
```

### Outputs

```json
{
  "eval_run_id": "uuid",
  "agent_config_id": "uuid",
  "accuracy_f1": 0.0,
  "guard_block_rate": 1.0,
  "mean_confidence": 0.0,
  "mean_cost_usd": 0.0,
  "mean_latency_ms": 0,
  "per_category": {
    "billing": {"precision": 0.0, "recall": 0.0, "f1": 0.0},
    "bug_report": {"precision": 0.0, "recall": 0.0, "f1": 0.0}
  },
  "regression_alert": false,
  "created_at": "ISO-8601"
}
```

### Allowed Tools

- `TriageAgent.process()` (called N times, once per eval case).
- Postgres `INSERT eval_runs`.
- No external integrations called (Linear, Telegram mocked in eval mode).

### Failure Modes

| Failure | Behavior |
|---|---|
| Eval case JSON malformed | Skip case; log warning; include in `skipped_count` |
| LLM call fails during eval | Mark case as `error`; continue; report error rate |
| F1 drops > 0.02 vs. prior run | Set `regression_alert=true`; log alert; do not block |

### Guardrails Applied

- All guardrails active (eval runs in production-equivalent mode).
- No writes to `tickets` table (eval mode flag suppresses DB writes).
- Costs incurred by eval runs tracked in cost_ledger under `eval` category.

### Role Sensitivity

Low. Eval output contains no PII; synthetic cases only. Accessible to `tenant_admin`.
