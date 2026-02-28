# gdev-agent — Architecture Spec v2.1

_Last updated: 2026-02-28 · Implementation contract for Codex and human reviewers.
All PRs must keep this document current. Spec version must be bumped on structural change._

---

## 1. Mission & Use Case

Every game studio processes a continuous stream of player messages: billing disputes, bug reports,
account problems, cheater tips, gameplay questions. Manual sorting causes SLA delays and missed tickets.

`gdev-agent` is an AI-powered triage service that sits behind any HTTP/webhook caller (n8n, Telegram,
Make, or direct HTTP). In a single round-trip it:

1. **Guards input** — rejects injection attempts and oversized text before any LLM call.
2. **Classifies** — uses Claude `tool_use` to determine category and urgency.
3. **Extracts** — pulls structured entities (transaction ID, error code, platform) from free text.
4. **Proposes** — builds an action with an explicit `risky` flag and `risk_reason`.
5. **Guards output** — scans LLM draft text for leaked secrets and unlisted URLs; enforces a confidence floor.
6. **Routes** — low-risk actions are auto-executed; high-risk ones enter a pending state and wait for `POST /approve`.

**Primary orchestrator:** n8n — all retry logic, approval UI, and audit logging live in n8n workflows,
not in application code. See `docs/N8N.md` for the full workflow blueprint.

**Measurable outcomes:**
- Classification accuracy ≥ 0.85 (per `eval/runner.py`)
- Guard block rate = 1.00 on all known injection patterns
- Approval latency < 1 h (enforced by `APPROVAL_TTL_SECONDS`)
- Cost ≤ $0.01/request (tracked via `AuditLogEntry.cost_usd` — currently not populated; see §12)

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
| Output guard (secrets + URL allowlist + confidence floor) | `app/guardrails/output_guard.py` | ✅ Implemented |
| JSON structured logger | `app/logging.py` | ✅ Implemented |
| X-Request-ID middleware | `app/main.py` | ✅ Implemented |
| Latency measurement (`latency_ms`) | `app/agent.py` | ✅ Implemented |
| SQLite event log (WAL mode) | `app/store.py` | ✅ Implemented |
| Redis approval store (durable, multi-instance) | `app/approval_store.py` | ✅ Implemented |
| TTL-based approval expiry (`expires_at`) | `app/approval_store.py · pop_pending()` | ✅ Implemented |
| `user_id` preserved through approval | `app/schemas.py · PendingDecision` | ✅ Implemented |
| Idempotency dedup (by `message_id`, 24 h) | `app/dedup.py` | ✅ Implemented |
| Legal-keyword risk in `propose_action()` | `app/agent.py` | ✅ Implemented |
| Error-code regex (anchored pattern) | `app/llm_client.py` | ✅ Implemented |
| Tool registry (`TOOL_REGISTRY` dict) | `app/tools/__init__.py` | ✅ Implemented |
| Webhook HMAC signature verification | `app/middleware/signature.py` | ✅ Implemented |
| Per-user rate limiting (Redis sliding window) | `app/middleware/rate_limit.py` | ✅ Implemented |
| Linear API integration | `app/integrations/linear.py` | ✅ Implemented |
| Telegram bot integration | `app/integrations/telegram.py` | ✅ Implemented |
| Google Sheets async audit log | `app/integrations/sheets.py` | ✅ Implemented |
| n8n workflow artifacts | `/n8n/` | ✅ Committed |
| Docker Compose full stack | `docker-compose.yml` | ✅ Implemented |
| Eval dataset (25 cases) | `eval/cases.jsonl` | ✅ Implemented |
| `ensure_ascii=False` in logs & store | `app/logging.py`, `app/store.py` | ✅ Implemented |
| Exception info (`exc_info`) in JSON logs | `app/logging.py` | ❌ Not implemented — see §12 |
| `RATE_LIMIT_BURST` enforcement | `app/middleware/rate_limit.py` | ❌ Config exists; not enforced — see §12 |
| LLM cost tracking (`cost_usd`) | `app/agent.py`, `AuditLogEntry` | ❌ Field present; always 0.0 — see §12 |

### 2.2 Repository Layout

```
gdev-agent/
├── app/
│   ├── main.py              # FastAPI app, lifespan, middleware stack, endpoints
│   ├── config.py            # pydantic-settings; Settings loaded once via get_settings()
│   ├── schemas.py           # All Pydantic models: request, response, internal
│   ├── agent.py             # AgentService: guard → classify → propose → output_guard → route
│   ├── llm_client.py        # LLMClient: Claude tool_use loop → TriageResult
│   ├── logging.py           # JsonFormatter + REQUEST_ID ContextVar
│   ├── store.py             # EventStore: optional SQLite WAL event log
│   ├── approval_store.py    # RedisApprovalStore: put/pop/get pending decisions
│   ├── dedup.py             # DedupCache: 24 h idempotency by message_id
│   ├── guardrails/
│   │   └── output_guard.py  # OutputGuard: secret scan, URL allowlist, confidence floor
│   ├── middleware/
│   │   ├── signature.py     # SignatureMiddleware: HMAC-SHA256 webhook verification
│   │   └── rate_limit.py    # RateLimitMiddleware: per-user Redis sliding window
│   ├── integrations/
│   │   ├── linear.py        # LinearClient: GraphQL issue creation
│   │   ├── telegram.py      # TelegramClient: send_message + send_approval_request
│   │   └── sheets.py        # SheetsClient: async audit log append
│   └── tools/
│       ├── __init__.py      # TOOL_REGISTRY: dict[str, ToolHandler]
│       ├── ticketing.py     # create_ticket() — Linear or stub
│       └── messenger.py     # send_reply() — Telegram or stub
├── eval/
│   ├── runner.py            # run_eval(): accuracy + per-label + guard_block_rate
│   └── cases.jsonl          # 25 labelled test cases
├── tests/                   # 11 test modules (fakeredis, httpx mocks)
├── n8n/
│   ├── workflow_triage.json
│   ├── workflow_approval_callback.json
│   └── README.md
├── docs/
│   ├── ARCHITECTURE.md      # this file
│   ├── N8N.md               # n8n workflow blueprint and integration contract
│   ├── PLAN.md              # delivered history + next iteration roadmap
│   └── REVIEW_NOTES.md      # engineering review checklist and historical findings
├── Dockerfile
├── docker-compose.yml       # agent + redis + n8n with healthchecks
├── requirements.txt
├── requirements-dev.txt     # pytest, fakeredis
└── .env.example
```

---

## 3. System Architecture (Current State)

```
┌────────────────────────────────────────────────────────────────────┐
│  External Callers                                                  │
│  Telegram Bot · n8n HTTP Request node · curl / Make               │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ POST /webhook
                               │ X-Webhook-Signature: sha256=<hmac>
                               │ X-Request-ID: <optional, echoed>
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│  app/main.py  [FastAPI + Middleware Stack]                         │
│                                                                    │
│  1. SignatureMiddleware   HMAC-SHA256 verify (skipped if secret    │
│                           unset — dev mode; logs WARNING)          │
│  2. RateLimitMiddleware   RATE_LIMIT_RPM req/60s per user_id       │
│                           (Redis INCR+EXPIRE; degrades gracefully) │
│  3. RequestIDMiddleware   reads/generates X-Request-ID ContextVar  │
│                                                                    │
│  Idempotency check                                                 │
│    Redis GET dedup:{message_id}                                    │
│    HIT  → return cached response body → done (logs dedup_hit)      │
│    MISS → continue processing                                      │
└──────────────────────────────┬─────────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│  app/agent.py  [AgentService.process_webhook()]                    │
│                                                                    │
│  _guard_input()                                                    │
│    len(text) ≤ MAX_INPUT_LENGTH (default 2 000 chars)             │
│    15-pattern injection check (case-insensitive substring)        │
│    → ValueError → HTTP 400                                         │
│                                                                    │
│  llm_client.run_agent()     Claude tool_use loop (max 5 turns)    │
│    classify_request   → ClassificationResult {category, urgency,  │
│                          confidence}                               │
│    extract_entities   → ExtractedFields {platform, txn_id, …}    │
│    draft_reply        → draft text (NOTE: currently unused —       │
│                          see §12 gap G)                           │
│    lookup_faq         → stub KB articles                           │
│    flag_for_human     → signals human review needed               │
│                                                                    │
│  propose_action()           risky=True when:                       │
│    category ∈ APPROVAL_CATEGORIES                                 │
│    urgency ∈ {high, critical}                                     │
│    confidence < AUTO_APPROVE_THRESHOLD                            │
│    text contains: lawyer | lawsuit | press | gdpr                 │
│                                                                    │
│  OutputGuard.scan(draft, confidence, action)                       │
│    secret regex: sk-ant-* | lin_api_* | Bearer …                  │
│       → blocked=True → HTTP 500 (internal error)                  │
│    URL allowlist: host not in URL_ALLOWLIST                        │
│       strip: remove URL, log output_guard_redacted                 │
│       reject: blocked=True → HTTP 500                             │
│    confidence < 0.5: mutate action.tool="flag_for_human",         │
│       action.risky=True (→ always takes pending path)             │
│                                                                    │
│  needs_approval? (= action.risky)                                  │
│    YES → RedisApprovalStore.put_pending()                          │
│          TelegramClient.send_approval_request() [fire-and-forget] │
│          Redis SET dedup:{message_id} = response                   │
│          EventStore.log_event("pending_created")                   │
│          → HTTP 200 {status:"pending", pending_id}                 │
│    NO  → TOOL_REGISTRY[action.tool](payload, user_id)             │
│            LinearClient.create_issue() [or stub]                  │
│            TelegramClient.send_message() [or stub]                │
│          Redis SET dedup:{message_id} = response                   │
│          SheetsClient.append_log() [async, background thread]     │
│          EventStore.log_event("action_executed")                   │
│          → HTTP 200 {status:"executed", action_result}             │
│                                                                    │
│  structured_log {request_id, event, category, latency_ms}         │
└────────────────────────────────────────────────────────────────────┘
                               │ (async / out-of-band)
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│  n8n Orchestration Layer                           /n8n/           │
│                                                                    │
│  [Triage Workflow]                                                 │
│    Telegram Trigger → normalize → POST /webhook                    │
│    status=="pending" → send Telegram approval buttons              │
│                      → Google Sheets: append pending row           │
│    status=="executed"→ Google Sheets: append executed row          │
│    error/timeout    → retry (max 3, backoff 30s/90s) → ops alert  │
│                                                                    │
│  [Approval Callback Workflow]                                      │
│    Telegram Trigger (callback_query) → extract pending_id          │
│    → answerCallbackQuery (within 30 s of button click)            │
│    → POST /approve {pending_id, approved, reviewer}                │
│    → send confirmation to approver                                 │
│    → Google Sheets: update decision row                            │
└────────────────────────────────────────────────────────────────────┘
```

---

## 4. API Contracts

All endpoints accept and return `application/json`.

### 4.1 `POST /webhook`

Main ingestion endpoint. Idempotent by `message_id` (24 h TTL via Redis dedup cache).

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
| `message_id` | `string` | No | Dedup key. If absent, a random UUID is generated and the response is **not** cached. Callers should always provide this. |
| `user_id` | `string` | No | Sender identifier. Preserved in `PendingDecision` for post-approval reply routing. |
| `text` | `string` | **Yes** | Free-form message. Min 1 char. Max `MAX_INPUT_LENGTH` (default 2 000). |
| `metadata` | `object` | No | Channel-specific extras (`chat_id`, `username`). Passed through to tool handlers; not parsed by agent. |

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
    "user_id":            "user_abc123",
    "platform":           "unknown",
    "transaction_id":     "TXN-9981",
    "error_code":         null,
    "game_title":         null,
    "reported_username":  null,
    "keywords":           ["crystals", "payment"]
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
    "user_id":            "user_abc123",
    "platform":           "unknown",
    "transaction_id":     "TXN-9981",
    "error_code":         null,
    "game_title":         null,
    "reported_username":  null,
    "keywords":           ["crystals", "payment"]
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
    "action":         { "tool": "create_ticket_and_reply", "payload": {}, "risky": true, "risk_reason": "..." },
    "draft_response": "Thanks for reporting this payment issue..."
  }
}
```

**Error responses:**

| HTTP | `detail` | Cause |
|------|----------|-------|
| 400 | `"Input exceeds max length (2000)"` | Text longer than `MAX_INPUT_LENGTH` |
| 400 | `"Input failed injection guard"` | Injection pattern matched |
| 401 | `"Invalid signature"` | HMAC mismatch (only when `WEBHOOK_SECRET` is set) |
| 429 | `"Rate limit exceeded"` | Per-`user_id` rate limit hit |
| 500 | `"Internal: output guard blocked response"` | Secret or disallowed URL in LLM draft |

**Idempotency note:** A duplicate `message_id` call on a `status: "pending"` response returns the cached response — same `pending_id`. If the original pending was subsequently approved or rejected, the cached `pending_id` is already consumed. n8n must treat HTTP 404 from `/approve` (with a cached `pending_id`) as terminal — do not retry.

---

### 4.2 `POST /approve`

Approve or reject a pending action. `pending_id` is **single-use** — `pop_pending()` atomically deletes the key. A second call with the same `pending_id` returns HTTP 404. Expired tokens also return HTTP 404.

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
| `pending_id` | `string` | **Yes** | 32-char hex token from `/webhook` response `pending.pending_id`. |
| `approved` | `bool` | **Yes** | `true` = execute action; `false` = reject with no action. |
| `reviewer` | `string` | No | Reviewer identifier. Logged for audit. **Not authenticated by the agent** — authentication is delegated to the calling system (n8n + Telegram private group scope). |

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
| 404 | `"pending_id not found"` | Token unknown, already consumed, or TTL-expired |

---

### 4.3 `GET /health`

```json
{ "status": "ok", "app": "gdev-agent" }
```

HTTP 200. Used by Docker healthchecks, n8n, and load balancers. Does not check downstream
dependencies (Redis, Anthropic API). Use separate monitoring for dependency health.

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
    "transaction_id": "TXN-9981",
    "reply_to":       "123456"
  },
  "risky":       true,
  "risk_reason": "category 'billing' requires approval"
}
```

| Field | Type | Notes |
|-------|------|-------|
| `tool` | `string` | Key into `TOOL_REGISTRY`. Must be a registered key before `execute_action()` is called. |
| `payload` | `object` | Forwarded verbatim to the tool handler. Handler must not assume any key is present. |
| `risky` | `bool` | `true` → action enters pending path; `execute_action()` is never called directly. |
| `risk_reason` | `string \| null` | Human-readable explanation shown to approver. `null` only when `risky=false`. |

**Risk-trigger conditions** (evaluated in `propose_action()`; all matching conditions set `risky=true`):

| Condition | `risk_reason` value |
|-----------|---------------------|
| `category ∈ APPROVAL_CATEGORIES` | `"category '{category}' requires approval"` |
| `urgency ∈ {high, critical}` | `"urgency '{urgency}' requires approval"` |
| `confidence < AUTO_APPROVE_THRESHOLD` | `"low confidence classification"` |
| Text contains: `lawyer`, `lawsuit`, `press`, `gdpr` | `"legal-risk keywords require approval"` |

Rules are evaluated in declaration order; **first matching reason** is stored. Multiple conditions can
fire simultaneously — `risky` becomes `true` on the first hit regardless.

**OutputGuard override:** If `confidence < 0.5`, OutputGuard additionally sets `action.tool = "flag_for_human"`
and `action.risky = True`. Since `flag_for_human` is not in `TOOL_REGISTRY`, this tool value is only valid
on the pending path (where `execute_action()` is never called). Do not add `flag_for_human` to
`TOOL_REGISTRY` — its semantics are "route to human", not "execute a handler".

---

### 5.2 Decision (`PendingDecision`)

A held action waiting for human approval. Stored in Redis with a TTL equal to `APPROVAL_TTL_SECONDS`.

```json
{
  "pending_id":     "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
  "reason":         "category 'billing' requires approval",
  "user_id":        "user_abc123",
  "expires_at":     "2026-02-28T11:00:00+00:00",
  "action": {
    "tool":        "create_ticket_and_reply",
    "payload":     { "..." },
    "risky":       true,
    "risk_reason": "category 'billing' requires approval"
  },
  "draft_response": "Thanks for reporting this payment issue..."
}
```

| Field | Type | Notes |
|-------|------|-------|
| `pending_id` | `string` | 32-char hex (`uuid4().hex`). 128-bit entropy — not guessable. |
| `reason` | `string` | Shown to approver in Telegram notification. |
| `user_id` | `string \| null` | Original sender. Passed to `execute_action()` on approval for reply routing. Must not be `None` when Telegram delivery is expected. |
| `expires_at` | `datetime (ISO 8601 UTC)` | `now(UTC) + APPROVAL_TTL_SECONDS`. Entries past this are evicted by `pop_pending()` → HTTP 404. |
| `action` | `ProposedAction` | Fully serialised action to execute on approval. |
| `draft_response` | `string` | Proposed reply text shown to approver; sent to user on approval. |

**Storage:** Redis key `pending:{pending_id}` with `EX = APPROVAL_TTL_SECONDS`. The application-level
`expires_at` field and the Redis TTL are set at creation time from the same value. Both checks apply:
Redis TTL prevents key accumulation; `expires_at` handles sub-second race conditions at the boundary.

**Serialisation invariant:** Always `model_dump(mode="json")` before storing. Always
`PendingDecision.model_validate_json(raw)` when reading back. Never pickle.

---

### 5.3 Approval (`ApproveRequest` / `ApproveResponse`)

See §4.2 for full JSON. `reviewer` is an opaque string logged for audit; it is not validated against
any identity store by the agent. Authentication of reviewer identity is delegated to the calling
system (n8n + Telegram inline buttons scoped to a private group).

**Production hardening:** Restrict `/approve` to the internal network (Docker bridge or VPC) or add a
shared `APPROVE_SECRET` header check. The agent currently accepts any caller who knows a `pending_id`.

---

### 5.4 Classification Result (`ClassificationResult`)

Output of the Claude `tool_use` loop; feeds `propose_action()`.

| Field | Type | Values |
|-------|------|--------|
| `category` | `string` | `bug_report`, `billing`, `account_access`, `cheater_report`, `gameplay_question`, `other` |
| `urgency` | `string` | `low`, `medium`, `high`, `critical` |
| `confidence` | `float` | `0.0`–`1.0`. Below `AUTO_APPROVE_THRESHOLD` (default 0.85) → risky. Below `0.5` → OutputGuard forces `flag_for_human`. |

**Fallback:** If Claude returns `stop_reason == "end_turn"` without calling `classify_request`,
`LLMClient` falls back to `ClassificationResult(category="other", urgency="low", confidence=0.0)`.
This is intentional and safe — confidence 0.0 triggers the approval gate via `AUTO_APPROVE_THRESHOLD`.
A `WARNING` log is emitted when the fallback fires.

---

### 5.5 Extracted Fields (`ExtractedFields`)

| Field | Type | Notes |
|-------|------|-------|
| `user_id` | `string \| null` | Falls back to `WebhookRequest.user_id`. |
| `platform` | `string` | `iOS`, `Android`, `PC`, `PS5`, `Xbox`, `unknown` |
| `game_title` | `string \| null` | As extracted by the model. |
| `transaction_id` | `string \| null` | Free-form; model extracts patterns like `TXN-9981`. |
| `error_code` | `string \| null` | Validated against `r"\b(?:ERR[-_ ]?\d{3,}\|E[-_]\d{4,})\b"` (case-insensitive). Non-conforming values are set to `null`. |
| `reported_username` | `string \| null` | Username reported by the player. |
| `keywords` | `list[string]` | Salient terms from the message. |

---

### 5.6 Audit Log Entry (`AuditLogEntry`)

Written asynchronously to Google Sheets after each completed action (executed, approved, or rejected).

| Column | Source | Notes |
|--------|--------|-------|
| `timestamp` | `datetime.now(UTC).isoformat()` | UTC ISO 8601 |
| `request_id` | `REQUEST_ID` ContextVar | Trace correlation ID |
| `message_id` | `WebhookRequest.message_id` | Original webhook field |
| `user_id` | SHA-256 hash of `user_id` | Never plaintext in audit log |
| `category` | `ClassificationResult.category` | |
| `urgency` | `ClassificationResult.urgency` | |
| `confidence` | `ClassificationResult.confidence` | |
| `action` | `ProposedAction.tool` | |
| `status` | Outcome | `"executed"`, `"approved"`, `"rejected"` |
| `approved_by` | `ApproveRequest.reviewer` or `"auto"` | |
| `ticket_id` | `action_result.ticket.ticket_id` | |
| `latency_ms` | `time.monotonic()` diff | End-to-end agent latency |
| `cost_usd` | — | Always `0.0` currently — see §12 |

---

## 6. Idempotency & Retry Semantics

### 6.1 Webhook Idempotency

Every `/webhook` call is idempotent by `message_id`.

**First call:**
1. Agent processes normally.
2. Full response body is serialised and stored in Redis: `dedup:{message_id}` with TTL = 86 400 s (24 h).

**Duplicate call (same `message_id` within 24 h):**
1. Middleware reads Redis key `dedup:{message_id}`.
2. Returns cached response body immediately. No LLM call. No duplicate ticket or approval entry.
3. Event `dedup_hit` is logged.

**When `message_id` is absent:**
- A UUID is generated internally.
- Response is **not** cached — no dedup guarantee for callers who omit `message_id`.

**Note on pending + dedup interaction:** A `status: "pending"` response is cached like any other.
A duplicate call returns the same cached `pending_id`. If that `pending_id` was already consumed
(approved/rejected), the caller's subsequent `/approve` call returns HTTP 404. n8n must treat 404
from `/approve` as terminal — not retriable.

### 6.2 Redis Key Namespace

| Key | TTL | Purpose |
|-----|-----|---------|
| `dedup:{message_id}` | 86 400 s | Idempotent response cache |
| `pending:{pending_id}` | `APPROVAL_TTL_SECONDS` | Durable approval decision |
| `ratelimit:{user_id}` | 60 s (sliding window) | Rate limit counter |

**Invariant:** These three prefixes are exclusive. No other Redis key may use these prefixes.
New features requiring Redis storage must define new prefixes and document them here.

### 6.3 Approval TTL & Expiry

- `PendingDecision.expires_at = now(UTC) + APPROVAL_TTL_SECONDS` (default 3 600 s).
- Redis key TTL is also set to `APPROVAL_TTL_SECONDS` at `put_pending()` time.
- `pop_pending()` uses `GETDEL` (atomic fetch + delete). If the returned entry is past `expires_at`,
  returns `None` and logs `pending_expired`.
- n8n Wait node timeout **must** be ≤ `APPROVAL_TTL_SECONDS − 60 s` to leave a buffer for the
  HTTP round-trip before the token expires.
- After TTL expiry: the player's message is silently dropped. There is no re-notification mechanism.
  See §12 for the planned improvement.

### 6.4 LLM Retry Policy

**Current:** No retry — transient Claude API failures surface as HTTP 500. n8n retries the full
`/webhook` request (per its retry chain in the Triage Workflow). If `message_id` was provided and
the first call failed before the dedup cache was written, the retry reprocesses normally. If the
first call partially succeeded (pending entry created), a second pending entry is created for the
same message. This is a narrow race condition with no current mitigation.

**Target (next iteration):** Add `tenacity` retry inside `LLMClient.run_agent()`:
- 3 attempts, initial delay 1 s, exponential backoff, max delay 30 s.
- Retry only on `anthropic.APIStatusError` with 5xx status codes.
- Do not retry 429 — surface as HTTP 503 to n8n to signal backpressure.
- Ensure pending entry is not created before the LLM call succeeds.

### 6.5 n8n Retry Strategy

All retry logic for `/webhook` HTTP failures lives in n8n:

| Attempt | Delay | Condition |
|---------|-------|-----------|
| 1 (initial) | 0 s | — |
| 2 | 30 s | HTTP 5xx or timeout |
| 3 | 90 s | HTTP 5xx or timeout |
| Give up | — | Notify ops channel via Telegram |

**HTTP 400 (guard block) and HTTP 404 are not retriable.** Configure n8n to not retry on 4xx.
**HTTP 500 from output guard** is also not retriable for the same input — the guard will fire again.
n8n should classify output guard 500 as terminal (requires operator investigation).

---

## 7. Security Model

### 7.1 Input Guard (`app/agent.py · _guard_input()`)

Runs synchronously before building LLM context. Raises `ValueError` → HTTP 400.

| Check | Detail |
|-------|--------|
| Length | `len(text) > MAX_INPUT_LENGTH` (default 2 000 chars) |
| Injection patterns | Case-insensitive substring match on 15 pattern classes |

**Current `INJECTION_PATTERNS` tuple (15 entries):**

```python
INJECTION_PATTERNS = (
    "ignore previous instructions",
    "system:",
    "[inst]", "[/inst]",
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

**Known false positive risk:** `"act as"` is a common English phrase. A message like "The NPC forces
you to act as a villain" is blocked with HTTP 400. Before adding new patterns, test against the full
`eval/cases.jsonl` dataset. Track false-positive rate as a metric in eval runs.

### 7.2 Output Guard (`app/guardrails/output_guard.py`)

Runs after `llm_client.run_agent()` returns, before the response leaves `AgentService`.

| Check | Pattern / Condition | Failure mode |
|-------|--------------------|----|
| Secret scan | `sk-ant-[a-zA-Z0-9\-]{20,}`, `lin_api_[a-zA-Z0-9]{20,}`, `Bearer\s+[a-zA-Z0-9+/=]{20,}` | `blocked=True` → HTTP 500 (no secret in `detail`) |
| URL allowlist | Host not in `URL_ALLOWLIST` | `OUTPUT_URL_BEHAVIOR=strip` → remove URL; `=reject` → HTTP 500 |
| Confidence floor | `confidence < 0.5` | Mutates `action.tool="flag_for_human"`, `action.risky=True` → pending path |

**Configurable:** `OUTPUT_GUARD_ENABLED` (default `true`). Set to `false` for local dev without risk.

**URL regex known limitation:** Pattern `r"https?://[^\s'\"<>]+"` can match trailing punctuation
(e.g., `https://kb.example.com/tips.` includes the trailing `.`). Host extraction via `urlparse`
still works correctly, but the stripped URL may leave a trailing `.` artifact in the text.

### 7.3 Webhook Signature Verification

Inbound `/webhook` calls must include:

```
X-Webhook-Signature: sha256=<hex_digest>
```

Where `<hex_digest>` = `HMAC-SHA256(WEBHOOK_SECRET, raw_request_body_bytes)`.

Middleware:
1. Reads raw body bytes before routing.
2. Computes expected signature.
3. Compares with `hmac.compare_digest()` — constant-time comparison, no timing oracle.
4. Mismatch → HTTP 401 `{"detail": "Invalid signature"}`.

When `WEBHOOK_SECRET` is unset, signature check is **skipped** (development mode). A `WARNING` log
is emitted at startup when running without a webhook secret. Set `WEBHOOK_SECRET` before any
internet-facing deployment.

### 7.4 Rate Limiting

Redis sliding-window rate limiter keyed by `user_id`:

| Env var | Default | Status |
|---------|---------|--------|
| `RATE_LIMIT_RPM` | `10` | Enforced — INCR+EXPIRE on `ratelimit:{user_id}` with 60 s TTL |
| `RATE_LIMIT_BURST` | `3` | **Config exists; not enforced** — see §12 |

Exceeded → HTTP 429 `{"detail": "Rate limit exceeded"}`.

If Redis is unavailable, rate limiting degrades gracefully (logs `WARNING`, allows request).

### 7.5 Authentication of `POST /approve`

`POST /approve` has no HTTP-level authentication by the agent. Authentication is delegated to the
calling system (n8n + Telegram inline buttons scoped to a private support group). The `reviewer`
field is logged for audit.

**Production hardening recommendation:** Restrict `/approve` to the Docker bridge network or a VPC
private subnet. Or add `APPROVE_SECRET` as a required request header, validated in a middleware.
The `pending_id` has 128-bit entropy and is not guessable — but it is transmitted in the webhook
response body and may appear in logs or proxies.

### 7.6 Secrets Management

```
.env (never commit — in .gitignore):
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
- `JsonFormatter` must not serialise environment variable values.
- `user_id` values are hashed (`sha256(user_id).hexdigest()`) in Sheets audit log.
- Missing `ANTHROPIC_API_KEY` causes immediate startup failure via `get_settings()`.
- Redis unreachable at startup causes `RuntimeError` (hard fail — idempotency broken without Redis).

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
    "cost_usd":    0.0
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
| `request_id` | `REQUEST_ID` ContextVar | Shared across all log lines for one HTTP request |
| `event` | `extra["event"]` | Machine-readable event type (see §8.3) |
| `context` | `extra["context"]` | Structured key-value pairs |
| `exc_info` | — | **Not currently emitted** — see §12 gap |

### 8.2 Request Correlation

1. Reads `X-Request-ID` header (or generates `uuid4().hex` if absent).
2. Sets `REQUEST_ID` ContextVar (`app/logging.py`).
3. Echoes the same ID in response `X-Request-ID` header.
4. `JsonFormatter.format()` reads the ContextVar and injects it into every log line.

All log lines for one HTTP request share the same `request_id`. Concurrent requests produce distinct values.

### 8.3 Event Taxonomy

| `event` | Level | Emitted when |
|---------|-------|-------------|
| `pending_created` | INFO | Action stored for human approval |
| `pending_approved` | INFO | Human approved; action executed |
| `pending_rejected` | INFO | Human rejected; no action taken |
| `pending_expired` | INFO | `pop_pending()` found entry past `expires_at` |
| `action_executed` | INFO | Action auto-executed without approval |
| `dedup_hit` | INFO | Duplicate `message_id`; cached response returned |
| `guard_blocked` | WARNING | Input guard raised `ValueError` |
| `output_guard_redacted` | INFO | Output guard stripped a URL from draft |
| `approval_notify_failed` | WARNING | Telegram approval notification failed |
| `rate_limit_bypass` | WARNING | Rate limiter skipped due to Redis unavailability |

### 8.4 Error Taxonomy

| Scenario | HTTP | `detail` |
|----------|------|----------|
| Input too long | 400 | `"Input exceeds max length (N)"` |
| Injection pattern detected | 400 | `"Input failed injection guard"` |
| `pending_id` not found or expired | 404 | `"pending_id not found"` |
| Invalid HMAC signature | 401 | `"Invalid signature"` |
| Rate limit exceeded | 429 | `"Rate limit exceeded"` |
| Output guard blocked response | 500 | `"Internal: output guard blocked response"` |
| Unknown tool in registry | 500 | FastAPI default (unhandled `ValueError`) |
| Unhandled exception | 500 | FastAPI default |

---

## 9. Extensibility

### 9.1 Adding a New Tool

Adding a new action tool requires changes to exactly two locations:

1. **Write the handler** in `app/tools/<name>.py`:
   ```python
   def my_tool(payload: dict[str, Any], user_id: str | None) -> dict[str, Any]:
       ...
   ```

2. **Register it** in `TOOL_REGISTRY` in `app/tools/__init__.py`:
   ```python
   TOOL_REGISTRY: dict[str, ToolHandler] = {
       "create_ticket_and_reply": _create_ticket_and_reply,
       "my_tool": my_tool,
   }
   ```

If the LLM should be able to invoke the tool autonomously, also add its schema to `TOOLS` in
`app/llm_client.py`. **When adding a new LLM-callable tool, both `TOOLS` and `TOOL_REGISTRY` must
be updated atomically.** A `TOOLS` entry without a `TOOL_REGISTRY` entry will cause a `ValueError`
at action dispatch time.

**No changes to `agent.py`, `main.py`, or `schemas.py` are required.**

### 9.2 Adding a New Support Category

1. Add the string to the `Category` `Literal` in `app/schemas.py`.
2. Add a draft reply branch in `AgentService._draft_response()`.
3. Add the value to `classify_request.input_schema.properties.category.enum` in `app/llm_client.py`.
4. Add eval cases covering the new category in `eval/cases.jsonl`.

### 9.3 Adding a New Input Channel

`/webhook` accepts any normalised `WebhookRequest`. New channels require only:
- A new n8n node (or thin adapter) normalising the channel payload into `WebhookRequest` fields.
- No changes to `AgentService`.

### 9.4 Tool Registry / TOOLS Sync Invariant

The set of tool names in `TOOL_REGISTRY` must be a superset of all tool names the LLM can produce
as `tool_use` block names. The set of LLM-callable tools is those in `TOOLS` in `llm_client.py`.
`flag_for_human` is exempt: it is LLM-callable but not in `TOOL_REGISTRY` because it always routes
to the pending path and `execute_action()` is never called for it.

CI check to enforce: `python -c "from app.tools import TOOL_REGISTRY; from app.llm_client import TOOLS; names = {t['name'] for t in TOOLS} - {'flag_for_human'}; assert names <= set(TOOL_REGISTRY)"`.

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
REDIS_URL=redis://redis:6379         # required; missing Redis → startup RuntimeError

# ── Output guard ──────────────────────────────────────────────────────────
OUTPUT_GUARD_ENABLED=true
URL_ALLOWLIST=                       # comma-separated allowed domains; empty = all URLs stripped
OUTPUT_URL_BEHAVIOR=strip            # strip | reject

# ── Security ─────────────────────────────────────────────────────────────
WEBHOOK_SECRET=                      # 256-bit random hex; unset = verification skipped (WARNING logged)
RATE_LIMIT_RPM=10                    # max requests per minute per user_id (enforced)
RATE_LIMIT_BURST=3                   # max requests in 10-second window (NOT YET ENFORCED — see §12)

# ── Integrations (all optional; absent = WARNING + stub fallback) ─────────
LINEAR_API_KEY=                      # lin_api_...
LINEAR_TEAM_ID=
TELEGRAM_BOT_TOKEN=
TELEGRAM_APPROVAL_CHAT_ID=           # private group for approval notifications
GOOGLE_SHEETS_CREDENTIALS_JSON=      # service-account JSON string or file path
GOOGLE_SHEETS_ID=                    # spreadsheet ID
```

---

## 11. n8n Integration Boundary

### 11.1 Responsibility Split

| What lives in n8n | What lives in application code |
|-------------------|-------------------------------|
| Retry logic (attempt count, backoff delays) | Business logic (classify, propose, guard) |
| Approval UI (Telegram inline buttons) | Approval store (Redis) |
| Google Sheets audit writes | SQLite event log |
| Input channel normalisation (Telegram → `WebhookRequest`) | Input guard (injection patterns, length) |
| Error alerting to ops channel | HTTP error taxonomy (status codes, `detail`) |
| Wait / resume on approval decision | TTL-based expiry of pending tokens |
| `answerCallbackQuery` within 30 s of button click | Telegram approval notification (fire-and-forget) |

### 11.2 Configuration Ownership

**Configurable only in n8n:**
- Telegram chat IDs (approval group, ops alert group).
- Google Sheets column mapping and sheet name.
- Retry delays and attempt counts.
- Ops alert thresholds and target channel.

**Configurable only in agent env vars:**
- `APPROVAL_CATEGORIES` — which categories require human approval.
- `AUTO_APPROVE_THRESHOLD` — confidence floor for auto-approval.
- `APPROVAL_TTL_SECONDS` — pending token validity. **n8n Wait node timeout must be ≤ this value.**

**Shared configuration (must stay in sync):**
- `WEBHOOK_SECRET` — set in agent `.env` and in n8n HTTP Request node credentials.
- Agent base URL — set in n8n HTTP Request node as `{{ $env.AGENT_BASE_URL }}`.

### 11.3 Failure Modes at the Boundary

| Failure | n8n behaviour | Agent behaviour |
|---------|---------------|-----------------|
| Agent returns HTTP 5xx or timeout | Retry (max 3, backoff 30 s/90 s), then ops alert | N/A |
| Agent returns HTTP 400 | **Do not retry** — terminal failure for this message | Returns `"Input failed injection guard"` |
| Agent returns HTTP 429 | Wait `Retry-After` (or 60 s), retry once; if 429 again → ops alert | Returns `"Rate limit exceeded"` |
| `/approve` returns HTTP 404 | **Do not retry** — token expired or consumed; tell user "expired" | Returns `"pending_id not found"` |
| Telegram API unavailable | Log, continue (fire-and-forget) | Logs `approval_notify_failed`, returns `status: "pending"` normally |
| Sheets API 429 | Retry once (60 s delay), then log and continue | N/A — n8n writes to Sheets |

---

## 12. Known Implementation Gaps

The following gaps are tracked against this spec. Each requires a PR with acceptance criteria before closure.

| ID | Gap | Impact | Recommended action |
|----|-----|--------|--------------------|
| G-1 | `exc_info` not captured in `JsonFormatter` | Tracebacks lost on `logger.exception()` calls | Add `self.formatException(record.exc_info) if record.exc_info else None` to payload |
| G-2 | `RATE_LIMIT_BURST` config exists but is not enforced | Security model overstates rate limiting guarantees | Implement 10-second sub-window check using a second Redis key, or remove the config field and the documentation reference |
| G-3 | `cost_usd` always `0.0` | Stated measurable outcome "≤ $0.01/request" unverifiable | Extract `usage.input_tokens` and `usage.output_tokens` from Claude API response in `LLMClient`; compute cost using model pricing; pass to `AgentService` for `AuditLogEntry` |
| G-4 | LLM `draft_reply` output unused | LLM drafts a better contextual response that is discarded | Wire `draft_text` from `draft_reply` tool result into `AgentService` as the draft; keep `_draft_response()` as a fallback only |
| G-5 | Duplicate Settings + Redis at module load | Two unchecked Redis pools; settings not lru_cache'd for middleware | Defer middleware initialisation to lifespan or pass the already-checked Redis client |
| G-6 | `asyncio.get_event_loop()` deprecated in Python 3.12 | `DeprecationWarning` in production; will be error in future Python | Replace with `asyncio.get_running_loop()` in `_append_audit_async()` |
| G-7 | Approval notification is fire-and-forget with no fallback | Telegram outage → player request silently expires after TTL | Add a polling endpoint or a recovery workflow that queries pending entries in Redis and re-notifies |
| G-8 | No CI check for TOOLS / TOOL_REGISTRY sync | Adding an LLM tool without a registry entry causes runtime `ValueError` | Add the CI assertion described in §9.4 |

---

## 13. Architectural Decisions

### ADR-1: Claude `tool_use` over prompt-engineered JSON output

**Decision:** Use Claude's `tool_use` API to enforce structured output schema at the API level rather than parsing JSON from assistant text.

**Alternatives considered:**
- Prompt engineering with `"Respond only in JSON: {schema}"` → model can hallucinate, omit fields, or return markdown fences.
- Response format with `json_object` mode → enforces JSON but not schema shape.

**Why chosen:** Tool use enforces field names, types, and enum values at the API level. Validation errors are caught in `_dispatch_tool()` and fall back to safe defaults. The model cannot return an invalid `category` or omit `confidence`.

**Trade-offs:** Tool use requires multiple API round-trips (one per tool call, up to 5). Adds latency (~100–200 ms per turn). Max 5 turns may be insufficient for complex triage requiring lookup + classify + draft.

---

### ADR-2: Redis as coordination layer (not in-process state)

**Decision:** Use Redis as the single coordination layer for approval decisions, idempotency, and rate limiting — not in-process dictionaries or databases.

**Alternatives considered:**
- In-memory dict (original implementation): correct for single-process, lost on restart, broken under multiple instances.
- PostgreSQL: correct and durable, but requires schema migration, ORM, and connection pool management — over-engineered for the data volume.
- SQLite for pending decisions: WAL mode allows concurrency, but cross-instance sharing requires a shared filesystem mount, complicating deployment.

**Why chosen:** Redis provides atomic operations (`GETDEL`, `INCR+EXPIRE`, `SET EX`), sub-millisecond latency, and horizontal scaling without process coupling. All three coordination needs (approval, dedup, rate limit) use the same Redis instance with isolated key namespaces.

**Trade-offs:** Redis is now a hard dependency. Redis failure breaks idempotency (by design — fail fast). Rate limiter alone degrades gracefully. Inconsistent failure policy is a documented gap (G-5 adjacent).

---

### ADR-3: Synchronous execution (no async task queue)

**Decision:** Execute LLM calls and tool handlers synchronously within the HTTP request/response cycle. FastAPI runs sync handlers in a thread pool.

**Alternatives considered:**
- Celery/Redis task queue: decouples HTTP response from LLM execution. Supports retries, timeouts, and priority queues. Adds operational complexity.
- Background asyncio tasks: still blocks thread pool workers without true async LLM client.
- True async (`anthropic.AsyncAnthropic`): enables async execution; requires converting all I/O to async.

**Why chosen:** Simplicity for MVP. FastAPI's thread pool (default ~36 threads) is sufficient for the expected traffic volume. The single round-trip contract (`POST /webhook` → response) is cleaner for n8n integration.

**Trade-offs:** Hard ceiling of ~36 concurrent LLM requests without configuration. Long-running Claude calls (up to 5 turns × ~2 s each = 10 s worst case) hold a thread for the full duration. Migration to async Claude client is the recommended path for scaling.

---

### ADR-4: n8n as the orchestration boundary

**Decision:** All retry logic, approval UI, channel normalisation, and audit log writes live in n8n — not in application code.

**Alternatives considered:**
- Application-level retry (`tenacity`): tighter control but duplicates logic that n8n already provides. Harder to adjust without code deployment.
- Separate retry service (Temporal/Conductor): correct for large-scale workflows but adds operational overhead disproportionate to the use case.

**Why chosen:** n8n provides a visual audit trail, built-in retry with backoff, non-developer-editable approval message templates, and parallel workflow execution. Support leads can adjust retry counts and approval messages without a code PR.

**Trade-offs:** n8n is a single-instance bottleneck in the open-source Docker setup. n8n workflow JSON format is not stable across major versions. Workflow logic is not version-controlled in the same way as application code (JSON diffs are unreadable).

---

### ADR-5: Guard failure policy — fail closed for output, fail open for rate limiting

**Decision:** Input guard and output guard failures are hard fails (HTTP 400/500). Rate limit Redis failure degrades gracefully (allow request, log warning). Approval store Redis failure is a hard fail.

**Alternatives considered:**
- Fail open for all Redis failures: acceptable for rate limiting, incorrect for idempotency.
- Fail closed for all failures: rate limit Redis failure → all requests blocked. Unacceptable availability impact.

**Why chosen:** Safety classification:
- Input/output guard: safety-critical — a false pass could send a harmful message. Fail closed.
- Rate limiting: DoS protection — graceful degradation is preferable to total outage.
- Approval store: correctness-critical — a missed store would create an orphaned pending action. Fail closed.
- Dedup cache: idempotency-critical by contract — fail closed (Redis must be up at startup).

**Trade-offs:** If Redis goes down during normal operation (after startup), approval store operations will raise and surface as HTTP 500. n8n will retry (correct), but retries will also fail until Redis recovers.

---

### ADR-6: Approval TTL as the expiry enforcement mechanism

**Decision:** Use dual TTL enforcement: Redis key TTL for automatic cleanup, plus application-level `expires_at` check in `pop_pending()` for sub-second boundary correctness.

**Alternatives considered:**
- Redis TTL only: possible race condition at the boundary where Redis hasn't expired the key but the business-level TTL has passed. Very narrow window but non-zero.
- Application-level only: Redis keys accumulate indefinitely if `pop_pending()` is never called (e.g., network partition). Requires a background sweep.

**Why chosen:** Both together. Redis TTL ensures automatic cleanup. Application-level `expires_at` is a defense-in-depth check that handles the narrow race at the boundary without requiring a background process.

**Trade-offs:** `expires_at` and Redis TTL are set from the same `APPROVAL_TTL_SECONDS` value at creation time. If `APPROVAL_TTL_SECONDS` is changed at runtime (env var change + restart), in-flight pending entries have a different TTL from newly created ones. Acceptable — restarts are expected to drain in-flight approvals.

---

### ADR-7: Idempotency TTL at 24 hours

**Decision:** Dedup cache TTL = 86 400 s (24 h). Not configurable.

**Alternatives considered:**
- Match `APPROVAL_TTL_SECONDS` (1 h): too short — n8n may retry a webhook message hours later if the first attempt partially failed.
- 7 days: correct for long retry windows, but accumulates cache entries without benefit (Telegram `message_id` values are per-chat and won't repeat within a day under normal usage).

**Why chosen:** 24 h covers all realistic n8n retry windows. Telegram `message_id` values are not reused within this window.

**Trade-offs:** A pending response cached for 24 h with a 1 h TTL on the underlying approval token will return a cached `pending_id` for up to 23 h after the token has expired. n8n must treat 404 from `/approve` as terminal — not retriable. This is documented and enforced in the n8n workflow contract.

---

### ADR-8: Tool registry with strict dispatch — no fallback

**Decision:** `execute_action()` raises `ValueError` on unknown tool name. No default handler.

**Alternatives considered:**
- Default no-op handler: silently drops unknown tools. Hard to debug.
- Log-and-continue: same problem — action is not executed, ticket not created.

**Why chosen:** An unknown tool name is always a programming error — either a tool was added to the LLM schema but not to the registry, or the LLM hallucinated a tool name. Both cases must fail loudly. The ValueError surfaces as HTTP 500, which triggers the n8n retry chain and ops alert.

**Trade-offs:** A Claude model update that introduces a new tool_use block name could cause production 500s if `TOOLS` is updated without `TOOL_REGISTRY`. Mitigated by the CI check described in §9.4 (gap G-8).
