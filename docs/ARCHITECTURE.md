# gdev-agent — Architecture

_Last updated: 2026-02-28 · Implementation contract for Codex and human reviewers. All PRs must keep this document current._

---

## 1. Mission & Use Case

Every game studio processes a continuous stream of player messages: billing disputes, bug reports,
account problems, cheater tips, gameplay questions. Manual sorting causes SLA delays and missed tickets.

`gdev-agent` is an AI-powered triage service that sits behind any HTTP/webhook caller (n8n, Telegram, Make, or direct HTTP). In a single round-trip it:

1. **Guards input** — rejects injection attempts and oversized text before any LLM call.
2. **Classifies** — uses Claude `tool_use` to determine category and urgency.
3. **Extracts** — pulls structured entities (transaction ID, error code, platform) from free text.
4. **Proposes** — builds an action with an explicit `risky` flag and `risk_reason`.
5. **Guards output** — _(target: PR-2)_ scans LLM draft text for leaked secrets and unlisted URLs.
6. **Routes** — low-risk actions are auto-executed; high-risk ones enter a pending state and wait for `POST /approve`.

**Primary orchestrator:** n8n — all retry logic, approval UI, and audit logging live in n8n workflows,
not in application code. See `docs/N8N.md` for the full workflow blueprint.

**Measurable outcomes:** classification accuracy ≥ 0.85, guard block rate 100% on known injection
patterns, approval latency < 1 h, cost ≤ $0.01/request.

---

## 2. Current System State (2026-02-28)

### 2.1 Component Status

| Component | Module | Status |
|-----------|--------|--------|
| FastAPI entrypoint | `app/main.py` | ✅ Implemented |
| Pydantic settings | `app/config.py` | ✅ Implemented |
| Request/response schemas | `app/schemas.py` | ✅ Implemented |
| Agent orchestration | `app/agent.py` | ✅ Implemented |
| Claude `tool_use` client | `app/llm_client.py` | ✅ Implemented |
| Input guard (15 pattern classes) | `app/agent.py · _guard_input()` | ✅ Implemented |
| JSON structured logger | `app/logging.py` | ✅ Implemented |
| X-Request-ID middleware | `app/main.py` | ✅ Implemented |
| Latency measurement (`latency_ms`) | `app/agent.py` | ✅ Implemented |
| SQLite event log (WAL mode) | `app/store.py` | ✅ Implemented |
| Pending approval store (in-memory + SQLite) | `app/store.py` | ✅ Implemented |
| TTL-based approval expiry (`expires_at`) | `app/store.py · pop_pending()` | ✅ Implemented |
| `user_id` preserved through approval | `app/schemas.py · PendingDecision` | ✅ Implemented |
| Legal-keyword risk in `propose_action()` | `app/agent.py` | ✅ Implemented |
| `needs_approval()` = `action.risky` | `app/agent.py` | ✅ Implemented |
| Error-code regex (anchored pattern) | `app/llm_client.py` | ✅ Implemented |
| `ensure_ascii=False` in logs & store | `app/logging.py`, `app/store.py` | ✅ Implemented |
| `configure_logging()` in lifespan | `app/main.py` | ✅ Implemented |
| Tool registry (`TOOL_REGISTRY` dict) | `app/tools/__init__.py` | ✅ Implemented |
| Output guard (secret scan + URL allowlist) | `app/guardrails/output_guard.py` | ✅ Implemented |
| Exception info in JSON log lines | `app/logging.py` | ❌ Not implemented |
| Redis approval store (durable, multi-instance) | `app/approval_store.py` | ✅ Implemented |
| Idempotency dedup (by `message_id`) | `app/dedup.py` | ✅ Implemented |
| Webhook HMAC signature verification | `app/middleware/signature.py` | ✅ Implemented |
| Rate limiting | `app/middleware/rate_limit.py` | ✅ Implemented |
| Linear API integration | `app/integrations/linear.py` | ✅ Implemented |
| Telegram bot integration | `app/integrations/telegram.py` | ✅ Implemented |
| n8n workflow artifacts | `/n8n/` | ✅ Committed — `workflow_triage.json`, `workflow_approval_callback.json`, `README.md` |
| Google Sheets audit log | `app/integrations/sheets.py` | ✅ Implemented |
| Eval dataset (25 cases) | `eval/cases.jsonl` | ✅ Implemented |

### 2.2 Repository Layout

```
gdev-agent/
├── app/
│   ├── main.py           # FastAPI app, lifespan, request-id middleware, endpoints
│   ├── config.py         # pydantic-settings; loaded once via get_settings()
│   ├── schemas.py        # All Pydantic request/response/internal models
│   ├── agent.py          # AgentService: guard → classify → propose → route
│   ├── llm_client.py     # LLMClient: Claude tool_use loop → TriageResult
│   ├── logging.py        # JsonFormatter + REQUEST_ID ContextVar
│   ├── store.py          # EventStore: in-memory pending dict + optional SQLite log
│   └── tools/
│       ├── __init__.py   # TOOL_REGISTRY to be added (PR-3)
│       ├── ticketing.py  # create_ticket() stub → Linear (PR-5)
│       └── messenger.py  # send_reply() stub → Telegram (PR-6)
├── eval/
│   ├── runner.py         # run_eval() — accuracy + per-label breakdown
│   └── cases.jsonl       # 6 labelled cases (expand to 25 in PR-8)
├── tests/
│   ├── test_approval_flow.py
│   └── test_guardrails_and_extraction.py
├── docs/
│   ├── ARCHITECTURE.md   # this file
│   ├── PLAN.md
│   ├── REVIEW_NOTES.md
│   └── N8N.md
└── .env.example
```

---

## 3. Target Architecture (n8n-First)

The following diagram represents the full system after all planned PRs are merged.

```
┌────────────────────────────────────────────────────────────────────┐
│  External Callers                                                  │
│  Telegram Bot · n8n HTTP Request node · curl / Make               │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ POST /webhook
                               │ X-Webhook-Signature: sha256=<hmac>  (PR-7)
                               │ X-Request-ID: <optional, echoed>
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│  app/main.py  [FastAPI + Middleware Stack]                         │
│                                                                    │
│  1. SignatureMiddleware   HMAC-SHA256 verify (PR-7)                │
│  2. RateLimitMiddleware   N req/min per user_id — Redis (PR-7)     │
│  3. RequestIDMiddleware   reads/generates X-Request-ID  ✅         │
│                                                                    │
│  Idempotency check (PR-1)                                          │
│    Redis GET dedup:{message_id}                                    │
│    HIT  → return cached response body → done                       │
│    MISS → continue processing                                      │
└──────────────────────────────┬─────────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│  app/agent.py  [AgentService]                                      │
│                                                                    │
│  _guard_input()                                          ✅        │
│    len(text) ≤ MAX_INPUT_LENGTH                                    │
│    15-pattern injection check                                      │
│    → ValueError → HTTP 400                                         │
│                    │                                               │
│  llm_client.run_agent()                                  ✅        │
│    Claude tool_use loop (max 5 turns)                              │
│    → ClassificationResult {category, urgency, confidence}          │
│    → ExtractedFields {platform, txn_id, error_code, …}            │
│                    │                                               │
│  propose_action()                                        ✅        │
│    risky=True when category ∈ APPROVAL_CATEGORIES                  │
│                   or urgency ∈ {high, critical}                    │
│                   or confidence < AUTO_APPROVE_THRESHOLD           │
│                   or legal tokens (lawyer/lawsuit/press/gdpr)      │
│                    │                                               │
│  _guard_output()                                         PR-2      │
│    secret regex scan (sk-ant-*, lin_api_*, Bearer …)              │
│    URL allowlist — strip or reject unlisted URLs                   │
│    confidence < 0.5 → force flag_for_human                         │
│                    │                                               │
│  needs_approval? (== action.risky)                                 │
│    YES ──▶ RedisApprovalStore.put_pending()              PR-1      │
│            notify_approval_channel()                     PR-6      │
│            Redis SET dedup:{message_id} = response       PR-1      │
│            → HTTP 200 {status:"pending", pending_id}               │
│    NO  ──▶ TOOL_REGISTRY[action.tool](payload, user_id) PR-3      │
│              LinearClient.create_issue()                 PR-5      │
│              TelegramClient.send_reply()                 PR-6      │
│            Redis SET dedup:{message_id} = response       PR-1      │
│            → HTTP 200 {status:"executed", action_result}           │
│                                                                    │
│  structured_log {request_id, event, category, latency_ms}  ✅     │
└────────────────────────────────────────────────────────────────────┘
                               │ (async / out-of-band)
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│  n8n Orchestration Layer                           /n8n/           │
│                                                                    │
│  [Triage Workflow]                                                 │
│    Telegram Trigger → normalize → POST /webhook                    │
│    status=="pending" → send Telegram approval buttons              │
│                      → Google Sheets: log pending row              │
│    status=="executed"→ Google Sheets: log executed row             │
│    error/timeout    → retry (max 3, backoff 30s) → ops alert       │
│                                                                    │
│  [Approval Callback Workflow]                                      │
│    Telegram Trigger (callback_query) → extract pending_id          │
│    → POST /approve {pending_id, approved, reviewer}                │
│    → answerCallbackQuery → send confirmation                       │
│    → Google Sheets: log decision row                               │
└────────────────────────────────────────────────────────────────────┘
```

---

## 4. API Contracts

All endpoints accept and return `application/json`.

### 4.1 `POST /webhook`

Main ingestion endpoint. Idempotent by `message_id` once PR-1 is deployed.

**Request body:**

```json
{
  "message_id": "tg_12345678",
  "user_id":    "user_abc123",
  "text":       "I bought crystals but they never arrived, TXN-9981",
  "metadata":   { "chat_id": "123456", "username": "player_nick" }
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `message_id` | `string` | No | Dedup key. If absent, a random UUID is generated and the response is **not** cached. |
| `user_id` | `string` | No | Sender identifier. Preserved in `PendingDecision` for post-approval reply routing. |
| `text` | `string` | **Yes** | Free-form message. Min 1 char. Max `MAX_INPUT_LENGTH` (default 2000). |
| `metadata` | `object` | No | Channel-specific extras (e.g., `chat_id`, `username`). Passed through; not parsed by agent. |

**Response — auto-executed (HTTP 200):**

```json
{
  "status": "executed",
  "classification": {
    "category":   "billing",
    "urgency":    "high",
    "confidence": 0.92
  },
  "extracted": {
    "user_id":        "user_abc123",
    "platform":       "unknown",
    "transaction_id": "TXN-9981",
    "error_code":     null,
    "game_title":     null,
    "reported_username": null,
    "keywords":       ["crystals", "payment"]
  },
  "action": {
    "tool":        "create_ticket_and_reply",
    "payload":     { "title": "[billing] support request", "urgency": "high" },
    "risky":       false,
    "risk_reason": null
  },
  "draft_response": "Thanks for reporting this payment issue. We are reviewing it and will update you shortly.",
  "action_result": {
    "ticket": { "ticket_id": "TKT-A1B2C3D4", "status": "created" },
    "reply":  { "delivery": "queued", "user_id": "user_abc123" }
  },
  "pending": null
}
```

**Response — pending approval (HTTP 200):**

```json
{
  "status": "pending",
  "classification": {
    "category":   "billing",
    "urgency":    "high",
    "confidence": 0.92
  },
  "extracted": {
    "user_id":        "user_abc123",
    "platform":       "unknown",
    "transaction_id": "TXN-9981",
    "error_code":     null,
    "game_title":     null,
    "reported_username": null,
    "keywords":       ["crystals", "payment"]
  },
  "action": {
    "tool":        "create_ticket_and_reply",
    "payload":     { "title": "[billing] support request", "urgency": "high" },
    "risky":       true,
    "risk_reason": "category 'billing' requires approval"
  },
  "draft_response": "Thanks for reporting this payment issue. We are reviewing it and will update you shortly.",
  "action_result": null,
  "pending": {
    "pending_id":     "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
    "reason":         "category 'billing' requires approval",
    "user_id":        "user_abc123",
    "expires_at":     "2026-02-28T11:00:00+00:00",
    "action":         { "...ProposedAction..." },
    "draft_response": "Thanks for reporting this payment issue..."
  }
}
```

**Error responses:**

| HTTP | `detail` | Cause |
|------|----------|-------|
| 400 | `"Input exceeds max length (2000)"` | Text longer than `MAX_INPUT_LENGTH` |
| 400 | `"Input failed injection guard"` | Injection pattern matched |
| 401 | `"Invalid signature"` | HMAC mismatch (PR-7) |
| 429 | `"Rate limit exceeded"` | Per-`user_id` rate limit hit (PR-7) |
| 500 | `"Internal: output guard blocked response"` | Secret or disallowed URL in LLM draft (PR-2) |

---

### 4.2 `POST /approve`

Approve or reject a pending action. Returns 404 if the `pending_id` is unknown or expired.

**Request body:**

```json
{
  "pending_id": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
  "approved":   true,
  "reviewer":   "support_lead_id"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `pending_id` | `string` | **Yes** | 32-char hex token from `/webhook` `pending.pending_id`. |
| `approved` | `bool` | **Yes** | `true` = execute action; `false` = reject with no action. |
| `reviewer` | `string` | No | Reviewer identifier. Logged for audit. Not authenticated here — authentication delegated to calling system. |

**Response — approved (HTTP 200):**

```json
{
  "status":     "approved",
  "pending_id": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
  "result": {
    "ticket": { "ticket_id": "TKT-A1B2C3D4", "status": "created" },
    "reply":  { "delivery": "queued", "user_id": "user_abc123" }
  }
}
```

**Response — rejected (HTTP 200):**

```json
{
  "status":     "rejected",
  "pending_id": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
  "result":     null
}
```

**Error responses:**

| HTTP | `detail` | Cause |
|------|----------|-------|
| 404 | `"pending_id not found"` | Token unknown, expired, or already consumed |

---

### 4.3 `GET /health`

```json
{ "status": "ok", "app": "gdev-agent" }
```

HTTP 200. Used by Docker healthchecks, n8n, and load balancers.

---

## 5. Internal Data Models

### 5.1 Action (`ProposedAction`)

What the agent wants to do, plus risk metadata. Stored inside `PendingDecision` until approved.

```json
{
  "tool":        "create_ticket_and_reply",
  "payload": {
    "title":          "[billing] support request",
    "text":           "<original message text>",
    "category":       "billing",
    "urgency":        "high",
    "transaction_id": "TXN-9981"
  },
  "risky":       true,
  "risk_reason": "category 'billing' requires approval"
}
```

| Field | Type | Notes |
|-------|------|-------|
| `tool` | `string` | Key into `TOOL_REGISTRY`. Determines the handler called by `execute_action()`. |
| `payload` | `object` | Forwarded verbatim to the tool handler. |
| `risky` | `bool` | `true` → action must be approved before execution. |
| `risk_reason` | `string \| null` | Human-readable explanation. `null` only when `risky=false`. |

**Risk-trigger conditions** (all evaluated in `propose_action()` — first match sets `reason`, all matching conditions set `risky=true`):**

| Condition | `risk_reason` value |
|-----------|---------------------|
| `category ∈ APPROVAL_CATEGORIES` | `"category '{category}' requires approval"` |
| `urgency ∈ {high, critical}` | `"urgency '{urgency}' requires approval"` |
| `confidence < AUTO_APPROVE_THRESHOLD` | `"low confidence classification"` |
| Text contains any of: `lawyer`, `lawsuit`, `press`, `gdpr` | `"legal-risk keywords require approval"` |

Rules are evaluated in declaration order; first matching reason is stored. Multiple conditions can
fire simultaneously — `risky` becomes `true` on the first hit regardless.

---

### 5.2 Decision (`PendingDecision`)

A held action waiting for human approval. Currently stored in-memory; target is Redis (PR-1).

```json
{
  "pending_id":     "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
  "reason":         "category 'billing' requires approval",
  "user_id":        "user_abc123",
  "expires_at":     "2026-02-28T11:00:00+00:00",
  "action": {
    "tool":        "create_ticket_and_reply",
    "payload":     { "...action payload..." },
    "risky":       true,
    "risk_reason": "category 'billing' requires approval"
  },
  "draft_response": "Thanks for reporting this payment issue. We are reviewing it and will update you shortly."
}
```

| Field | Type | Notes |
|-------|------|-------|
| `pending_id` | `string` | 32-char hex (`uuid4().hex`). Not guessable by brute force. |
| `reason` | `string` | Shown to approver in Telegram notification. |
| `user_id` | `string \| null` | Original sender. Passed to `execute_action()` on approval so the reply reaches the correct user. |
| `expires_at` | `datetime (ISO 8601 UTC)` | `now() + APPROVAL_TTL_SECONDS`. Entries past this timestamp are evicted by `pop_pending()` and return `None` → HTTP 404. |
| `action` | `ProposedAction` | Fully serialised action to execute on approval. |
| `draft_response` | `string` | Proposed reply text. Shown to approver; sent to user on approval. |

**Storage backends:**

| Backend | Where | Multi-instance | Survives restart | Status |
|---------|-------|---------------|-----------------|--------|
| In-memory `dict` | `app/store.py` | ❌ No | ❌ No | Current |
| Redis with TTL | `app/approval_store.py` | ✅ Yes | ✅ Yes | PR-1 target |

---

### 5.3 Approval (`ApproveRequest` / `ApproveResponse`)

See §4.2 for full JSON. `reviewer` is an opaque string logged for audit; it is not validated against
any identity store by the agent. Authentication of reviewer identity is delegated to the calling
system (n8n with Telegram inline buttons scoped to a private group).

---

### 5.4 Classification Result (`ClassificationResult`)

Output of the Claude `tool_use` loop; feeds `propose_action()`.

| Field | Type | Values |
|-------|------|--------|
| `category` | `string` | `bug_report`, `billing`, `account_access`, `cheater_report`, `gameplay_question`, `other` |
| `urgency` | `string` | `low`, `medium`, `high`, `critical` |
| `confidence` | `float` | `0.0`–`1.0`. Below `AUTO_APPROVE_THRESHOLD` (default 0.85) → risky. Below `0.5` → forced `flag_for_human` (PR-2 output guard). |

---

### 5.5 Extracted Fields (`ExtractedFields`)

Structured entities pulled from free-form text by the Claude `extract_entities` tool.

| Field | Type | Pattern / Notes |
|-------|------|-----------------|
| `user_id` | `string \| null` | From context; falls back to `WebhookRequest.user_id`. |
| `platform` | `string` | `iOS`, `Android`, `PC`, `PS5`, `Xbox`, `unknown` |
| `game_title` | `string \| null` | As extracted by the model. |
| `transaction_id` | `string \| null` | Free-form; model extracts patterns like `TXN-9981`. |
| `error_code` | `string \| null` | Validated against regex `(?:ERR[-_ ]?\d{3,}\|E[-_]\d{4,})` (case-insensitive). Only conforming strings are kept. |
| `reported_username` | `string \| null` | Username reported by the player. |
| `keywords` | `list[string]` | Salient terms from the message. |

---

## 6. Idempotency & Retry Semantics

### 6.1 Webhook Idempotency (PR-1)

Every `/webhook` call is idempotent by `message_id`.

**First call:**
1. Agent processes normally.
2. Full response body is serialised and stored in Redis: `dedup:{message_id}` with TTL = 86 400 s (24 h).

**Duplicate call (same `message_id` within 24 h):**
1. Middleware reads Redis key `dedup:{message_id}`.
2. Returns cached response body immediately.
3. No LLM call, no duplicate ticket, no duplicate approval entry.
4. Event `dedup_hit` is logged.

**When `message_id` is absent:**
- A UUID is generated internally.
- Response is **not** cached (no dedup guarantee for callers who omit `message_id`).

### 6.2 Redis Key Namespacing

| Key | TTL | Purpose |
|-----|-----|---------|
| `dedup:{message_id}` | 86 400 s | Idempotent response cache |
| `pending:{pending_id}` | `APPROVAL_TTL_SECONDS` | Durable approval decision |
| `ratelimit:{user_id}` | 60 s (sliding window) | Rate limit counter (PR-7) |

### 6.3 Approval TTL & Expiry

- `PendingDecision.expires_at = now() + APPROVAL_TTL_SECONDS` (default 3 600 s).
- `pop_pending()` evicts entries past `expires_at` and returns `None` → HTTP 404.
- Expired decisions are logged as `pending_expired`.
- n8n's Wait node timeout **must** be ≤ `APPROVAL_TTL_SECONDS` so the workflow fails cleanly rather than calling `/approve` after the token has expired.

### 6.4 LLM Retry

Current: no retry — transient Claude API failures surface as HTTP 500.

Target (post-MVP): add `tenacity` retry with:
- 3 attempts, initial delay 1 s, exponential backoff, max delay 30 s.
- Retry only on `anthropic.APIError` with 5xx status.
- Do **not** auto-retry 429 (rate limit) — surface as HTTP 503 to signal backpressure.

### 6.5 n8n Retry Strategy

All retry logic for `/webhook` failures lives in n8n:

| Attempt | Delay | Condition |
|---------|-------|-----------|
| 1 (initial) | 0 s | — |
| 2 | 30 s | HTTP 5xx or timeout |
| 3 | 90 s | HTTP 5xx or timeout |
| Give up | — | Notify ops channel via Telegram |

Configure n8n's global Error Workflow to catch uncaught node failures.

---

## 7. Security Model

### 7.1 Input Guard (`app/agent.py · _guard_input()`)

Runs synchronously before building LLM context. Raises `ValueError` → HTTP 400.

| Check | Detail |
|-------|--------|
| Length | `len(text) > MAX_INPUT_LENGTH` (default 2 000 chars) |
| Injection patterns | Case-insensitive substring match on 15 pattern classes (see below) |

**Current `INJECTION_PATTERNS` tuple (15 entries):**

```python
INJECTION_PATTERNS = (
    "ignore previous instructions",
    "system:",
    "[inst]",
    "[/inst]",
    "act as",
    "you are now",
    "forget all",
    "disregard",
    "developer mode",
    "jailbreak",
    "bypass",
    "pretend you",
    "<|system|>",
    "[system]",
    "###instruction",
)
```

The guard is a fast-path block; it does not replace output-side validation.

### 7.2 Output Guard (`app/guardrails/output_guard.py`) — PR-2

Runs after `llm_client.run_agent()` returns, before the response leaves `AgentService`.

| Check | Pattern / Condition | Failure mode |
|-------|--------------------|----|
| Secret scan | `sk-ant-[a-zA-Z0-9\-]{20,}`, `lin_api_[a-zA-Z0-9]{20,}`, `Bearer [a-zA-Z0-9+/=]{20,}` | HTTP 500 (internal error — do not leak detail) |
| URL allowlist | Any URL in `draft_response` whose host is not in `URL_ALLOWLIST` | Strip URL (`OUTPUT_URL_BEHAVIOR=strip`) or HTTP 500 (`reject`) |
| Confidence floor | `confidence < 0.5` | Override: `action.tool = "flag_for_human"`, `action.risky = True` |

Configurable via `OUTPUT_GUARD_ENABLED` (default `true`). Set to `false` for local development without risk.

### 7.3 Webhook Signature Verification — PR-7

Inbound `/webhook` calls from n8n must include:

```
X-Webhook-Signature: sha256=<hex_digest>
```

Where `<hex_digest>` = `HMAC-SHA256(WEBHOOK_SECRET, raw_request_body_bytes)`.

Middleware (first in stack):
1. Read raw body bytes before routing.
2. Compute expected signature.
3. Compare with `hmac.compare_digest()` (constant-time — no timing oracle).
4. Mismatch → HTTP 401 `{"detail": "Invalid signature"}`.

When `WEBHOOK_SECRET` is unset, signature check is **skipped** (development mode). Set it before exposing to the internet.

### 7.4 Rate Limiting — PR-7

Redis sliding-window rate limiter keyed by `user_id`:

| Env var | Default | Meaning |
|---------|---------|---------|
| `RATE_LIMIT_RPM` | `10` | Max requests per minute per `user_id` |
| `RATE_LIMIT_BURST` | `3` | Max requests in any 10-second window |

Exceeded → HTTP 429 `{"detail": "Rate limit exceeded"}`.

If Redis is unavailable, rate limiting degrades gracefully (logs warning, allows request).

### 7.5 Authentication of `POST /approve`

`POST /approve` has no HTTP-level authentication by the agent. Authentication is delegated to the calling system (n8n workflow + Telegram inline buttons scoped to a private support group). The `reviewer` field is logged for audit.

For production hardening: restrict `/approve` to internal network (VPC/Docker bridge) or add a shared `APPROVE_SECRET` header check.

### 7.6 Secrets Management

```
.env (never commit — add to .gitignore):
  ANTHROPIC_API_KEY=sk-ant-...
  LINEAR_API_KEY=lin_api_...
  TELEGRAM_BOT_TOKEN=...
  TELEGRAM_APPROVAL_CHAT_ID=...
  WEBHOOK_SECRET=<256-bit random hex>
  REDIS_URL=redis://redis:6379

Production: Docker secrets / AWS Secrets Manager / HashiCorp Vault
```

Rules enforced in code and CI:
- `.gitignore` includes `.env`, `*.key`, `secrets/`.
- `git grep -rn "sk-ant\|lin_api_\|Bearer "` must return no results inside `app/`.
- `JsonFormatter` must not serialise environment variables.
- `user_id` values are hashed (`sha256(user_id)`) in production log output.
- Missing `ANTHROPIC_API_KEY` causes immediate startup failure with a clear error message.

---

## 8. Observability

### 8.1 Log Format

Every line written to stdout is a JSON object on a single line.

```json
{
  "timestamp":  "2026-02-28T10:00:00.123456+00:00",
  "level":      "INFO",
  "logger":     "app.agent",
  "message":    "action executed",
  "request_id": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
  "event":      "action_executed",
  "context": {
    "category":    "billing",
    "urgency":     "high",
    "confidence":  0.92,
    "pending_id":  null,
    "latency_ms":  312,
    "cost_usd":    0.003
  }
}
```

**Field contracts:**

| Field | Source | Notes |
|-------|--------|-------|
| `timestamp` | `record.created` (Unix float → ISO 8601 UTC) | Event time, not serialisation time |
| `level` | `record.levelname` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `logger` | `record.name` | e.g., `app.agent`, `app.main` |
| `message` | `record.getMessage()` | Human-readable summary |
| `request_id` | `REQUEST_ID` ContextVar | Shared across all log lines for a single HTTP request |
| `event` | `extra["event"]` | Machine-readable event type (see §8.3) |
| `context` | `extra["context"]` | Structured key-value pairs for the event |
| `exc_info` | `self.formatException(record.exc_info)` | Present only when `logger.exception()` is used (PR target) |

### 8.2 Request Correlation

FastAPI middleware in `app/main.py`:
1. Reads `X-Request-ID` header (or generates `uuid4().hex` if absent).
2. Sets `REQUEST_ID` ContextVar (`app/logging.py`).
3. Echoes the same ID in response `X-Request-ID` header.
4. `JsonFormatter.format()` reads the ContextVar and injects it into every log line.

All log lines for one HTTP request share the same `request_id`. Concurrent requests produce distinct values.

### 8.3 Event Types

| `event` | Emitted when |
|---------|-------------|
| `pending_created` | Action stored for human approval |
| `pending_resolved` | Approval store entry fetched (approve or reject path) |
| `pending_approved` | Human approved; action executed |
| `pending_rejected` | Human rejected; no action taken |
| `pending_expired` | `pop_pending()` found an entry past `expires_at` |
| `action_executed` | Action auto-executed without approval |
| `dedup_hit` | Duplicate `message_id`; cached response returned (PR-1) |
| `guard_blocked` | Input guard raised `ValueError` |
| `output_guard_redacted` | Output guard stripped a URL or secret from draft (PR-2) |

### 8.4 Error Taxonomy (HTTP Responses)

| Scenario | HTTP | `detail` |
|----------|------|----------|
| Input too long | 400 | `"Input exceeds max length (N)"` |
| Injection pattern detected | 400 | `"Input failed injection guard"` |
| `pending_id` not found or expired | 404 | `"pending_id not found"` |
| Invalid HMAC signature | 401 | `"Invalid signature"` |
| Rate limit exceeded | 429 | `"Rate limit exceeded"` |
| Output guard blocked response | 500 | `"Internal: output guard blocked response"` |
| Unhandled exception | 500 | FastAPI default |

---

## 9. Extensibility

### 9.1 Adding a New Tool (PR-3+)

After the tool registry is in place (PR-3), adding a new tool requires changes to exactly three locations:

1. **Write the handler** in `app/tools/<name>.py`:
   ```python
   def my_tool(payload: dict[str, Any], user_id: str | None) -> dict[str, Any]:
       ...
   ```

2. **Register it** in `TOOL_REGISTRY` in `app/tools/__init__.py`:
   ```python
   TOOL_REGISTRY: dict[str, Callable[[dict, str | None], dict]] = {
       "create_ticket_and_reply": _create_ticket_and_reply,
       "my_tool": my_tool,
   }
   ```

3. **Add the tool schema** to `TOOLS` in `app/llm_client.py` if the LLM should be able to invoke it autonomously.

No changes to `agent.py`, `main.py`, or `schemas.py` are required.

### 9.2 Adding a New Support Category

1. Add the string to the `Category` `Literal` in `app/schemas.py`.
2. Add a draft reply branch in `AgentService._draft_response()`.
3. Add the value to `classify_request.input_schema.properties.category.enum` in `app/llm_client.py`.
4. Add eval cases covering the new category in `eval/cases.jsonl`.

### 9.3 Adding a New Input Channel

`/webhook` accepts any normalised `WebhookRequest`. New channels require only:
- A new n8n node (or thin adapter) normalising the channel payload into the `WebhookRequest` fields.
- No changes to `AgentService`.

---

## 10. Environment Variables

```bash
# ── App ──────────────────────────────────────────────────────────────────
APP_NAME=gdev-agent
APP_ENV=dev                          # dev | staging | prod
LOG_LEVEL=INFO

# ── LLM — required at startup ────────────────────────────────────────────
ANTHROPIC_API_KEY=                   # sk-ant-... — missing → startup failure
ANTHROPIC_MODEL=claude-sonnet-4-6

# ── Agent behaviour ───────────────────────────────────────────────────────
MAX_INPUT_LENGTH=2000
AUTO_APPROVE_THRESHOLD=0.85          # confidence ≥ this → auto-approve (low/medium urgency only)
APPROVAL_CATEGORIES=billing,account_access
APPROVAL_TTL_SECONDS=3600            # pending tokens expire after N seconds

# ── Storage ───────────────────────────────────────────────────────────────
SQLITE_LOG_PATH=                     # empty = SQLite disabled; set to file path to enable
REDIS_URL=redis://redis:6379         # required for PR-1+ (idempotency + durable approval store)

# ── Output guard — PR-2 ───────────────────────────────────────────────────
OUTPUT_GUARD_ENABLED=true
URL_ALLOWLIST=                       # comma-separated allowed domains, e.g. kb.example.com
OUTPUT_URL_BEHAVIOR=strip            # strip | reject

# ── Security — PR-7 ──────────────────────────────────────────────────────
WEBHOOK_SECRET=                      # 256-bit random hex; if unset, verification is skipped
RATE_LIMIT_RPM=10                    # max requests per minute per user_id
RATE_LIMIT_BURST=3                   # max requests in any 10-second window per user_id

# ── Integrations ─────────────────────────────────────────────────────────
LINEAR_API_KEY=                      # lin_api_... — required for PR-5 (Linear tickets)
LINEAR_TEAM_ID=                      # Linear team ID
TELEGRAM_BOT_TOKEN=                  # required for PR-6 (Telegram bot)
TELEGRAM_APPROVAL_CHAT_ID=           # chat/group ID for approval notifications
GOOGLE_SHEETS_CREDENTIALS_JSON=      # path to service-account JSON — required for PR-9
GOOGLE_SHEETS_ID=                    # Google Sheets spreadsheet ID
```

**Startup validation:** `ANTHROPIC_API_KEY` is validated at startup by `pydantic-settings`. All other integration keys are optional but cause `RuntimeError` at first use if absent when the integration is invoked.

---

## 11. n8n Integration Boundary

| What lives in n8n | What lives in application code |
|-------------------|-------------------------------|
| Retry logic (attempt count, backoff delays) | Business logic (classify, propose, guard) |
| Approval UI (Telegram inline buttons) | Approval store (in-memory / Redis) |
| Audit log write (Google Sheets) | Event log write (SQLite stdout) |
| Input channel normalisation (Telegram → `WebhookRequest`) | Input guard (injection patterns, length check) |
| Routing between workflows | Action execution (Linear, Telegram reply) |
| Error alerting to ops channel | HTTP error taxonomy (status codes, `detail`) |
| Wait / resume on approval decision | TTL-based expiry of pending tokens |

**Configurable only in n8n** (no env var in agent):
- Telegram chat IDs for approval groups.
- Google Sheets column mapping and sheet name.
- Retry delays and attempt counts.
- Ops alert thresholds and target channel.

**Configurable only in agent env vars** (n8n reads via HTTP response, not config):
- `APPROVAL_CATEGORIES` — which categories require human approval.
- `AUTO_APPROVE_THRESHOLD` — confidence floor for auto-approval.
- `APPROVAL_TTL_SECONDS` — how long a pending token is valid. **n8n Wait node timeout must be ≤ this value.**

**Shared configuration** (must be kept in sync):
- `WEBHOOK_SECRET` — set in agent `.env` **and** in n8n HTTP Request node credentials.
- Agent base URL — set in n8n HTTP Request node URL field.
