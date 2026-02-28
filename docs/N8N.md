# gdev-agent — n8n Workflow Guide

_Implementation contract for the n8n orchestration layer. Read alongside `docs/ARCHITECTURE.md §11`._

---

## 1. Overview

n8n is the **sole orchestration layer** for all operational concerns: retry logic, approval UI,
channel normalisation, and audit logging. Application code (`app/`) does not contain retry loops,
Telegram keyboard builders, or Google Sheets writers — these live in n8n workflows.

### Why n8n?

| Reason | Detail |
|--------|--------|
| Visual audit trail | Every execution run is inspectable in the n8n UI without reading logs |
| Non-dev editable | Support leads can adjust retry counts or approval messages without code changes |
| Built-in retry | HTTP Request nodes have configurable retry with backoff |
| Parallel workflows | Triage and approval flows are independent; failures in one do not block the other |

### What lives in n8n vs. code

| n8n | Application code |
|-----|-----------------|
| Retry logic | Business logic (classify, propose, guard) |
| Approval Telegram UI | Approval store (Redis) |
| Google Sheets audit writes | SQLite event log |
| Channel normalisation | Input guard |
| Error alerting | HTTP error taxonomy |
| Wait / resume on approval | TTL-based pending expiry |

---

## 2. Workflows

Two workflows are committed under `/n8n/`:

| File | Purpose |
|------|---------|
| `n8n/workflow_triage.json` | Main flow: Telegram message → agent → approval or log |
| `n8n/workflow_approval_callback.json` | Approval flow: inline button click → `/approve` → log |

Import both via **n8n Settings → Workflows → Import from file**.
Minimum n8n version: `1.x` (see `docker-compose.yml` for pinned version).

---

## 3. Triage Workflow — Node-by-Node Blueprint

```
[1: Telegram Trigger]
        │ on: message (type=message only, not edited_message)
        │ produces: { message_id, text, chat_id, from.id, from.username }
        ▼
[2: Function — Normalize]
        │ builds WebhookRequest body
        │ casts message_id to string
        │ sets metadata.chat_id from message.chat.id
        ▼
[3: HTTP Request — POST /webhook]
        │ URL: http://agent:8000/webhook
        │ Method: POST
        │ Auth: Header Auth (X-Webhook-Signature: sha256=<hmac>)
        │ Header: X-Request-ID: {{ $execution.id }}
        │ Body: { message_id, user_id, text, metadata }
        │ Timeout: 30 s
        │ Retry on failure: No (retry chain is explicit below)
        ▼
[4: IF — status == "pending"?]
        │ Condition: {{ $json.status }} === "pending"
        │
        ├─── YES ──────────────────────────────────────────────────────┐
        │                                                              │
        │   [5a: HTTP Request — Send Approval Message]                │
        │        URL: https://api.telegram.org/bot{TOKEN}/sendMessage  │
        │        Body: {                                               │
        │          chat_id: TELEGRAM_APPROVAL_CHAT_ID,                │
        │          text: "🔔 Approval Required\n\n                    │
        │                Category: {{ $json.classification.category }} │
        │                Urgency:  {{ $json.classification.urgency }}\n │
        │                Reason:   {{ $json.action.risk_reason }}\n\n  │
        │                Draft reply:\n{{ $json.draft_response }}",    │
        │          reply_markup: {                                     │
        │            inline_keyboard: [[                               │
        │              { text: "✅ Approve",                           │
        │                callback_data: "approve:{{ $json.pending.pending_id }}" }, │
        │              { text: "❌ Reject",                            │
        │                callback_data: "reject:{{ $json.pending.pending_id }}" }  │
        │            ]]                                                │
        │          }                                                   │
        │        }                                                     │
        │                                                              │
        │   [5b: Google Sheets — Append Pending Row]                  │
        │        (see §7 Audit Log Columns)                           │
        │        status = "pending"                                    │
        │        approved_by = ""                                      │
        │        ticket_id = ""                                        │
        │                                                              │
        └─── NO (status == "executed") ────────────────────────────────┤
                                                                       │
            [6a: Google Sheets — Append Executed Row]                 │
                 status = "executed"                                   │
                 approved_by = "auto"                                  │
                 ticket_id = {{ $json.action_result.ticket.ticket_id }}│
                                                                       │
[7: Error Handler] ◄────────────────────────────────────────────────── (on node 3 failure)
        │ trigger: HTTP 5xx or timeout from node 3
        │
        ├── attempt < 3?
        │     YES → [Wait: 30 s (attempt 2) or 90 s (attempt 3)] → retry node 3
        │     NO  → [8: Telegram — Notify Ops Channel]
        │                 text: "❌ Agent unreachable after 3 attempts\n
        │                        request_id: {{ $execution.id }}\n
        │                        error: {{ $json.error }}"
        │                 chat_id: OPS_TELEGRAM_CHAT_ID
        └──────────────────────────────────────────────────────────────
```

### Node Configurations

#### Node 1: Telegram Trigger

| Setting | Value |
|---------|-------|
| Credential | Telegram Bot API (`TELEGRAM_BOT_TOKEN`) |
| Update types | `message` only |
| Filter | Do not include `edited_message`, `channel_post`, `callback_query` — those are handled by the Approval Callback Workflow |

#### Node 2: Function — Normalize

```javascript
// n8n Function node
const msg = $input.item.json.message;
return [{
  json: {
    message_id: String(msg.message_id),
    user_id:    String(msg.from.id),
    text:       msg.text.trim(),
    metadata: {
      chat_id:  String(msg.chat.id),
      username: msg.from.username || null
    }
  }
}];
```

Edge cases:
- `msg.text` may be `undefined` for sticker/photo messages — return early with a safe default or skip.
- `msg.from.id` is always present for private/group messages.

#### Node 3: HTTP Request — POST /webhook

| Setting | Value |
|---------|-------|
| URL | `{{ $env.AGENT_BASE_URL }}/webhook` |
| Method | POST |
| Body (JSON) | `{{ $json }}` (pass entire output of node 2) |
| Header — `X-Webhook-Signature` | `sha256={{ hmac($env.WEBHOOK_SECRET, $body) }}` |
| Header — `X-Request-ID` | `{{ $execution.id }}` |
| Timeout | 30 000 ms |
| Follow redirects | Yes |
| Retry on failure | **No** (retry is handled explicitly in node 7) |

#### Node 4: IF Branch

```
{{ $json.status }} === "pending"
```

#### Node 5a: HTTP Request — Send Approval Message

Calls the Telegram `sendMessage` API. Uses `TELEGRAM_BOT_TOKEN` credential.
The `chat_id` is `{{ $env.TELEGRAM_APPROVAL_CHAT_ID }}` — the internal support group.
**Do not** use `metadata.chat_id` (that is the user's private chat).

#### Node 5b / 6a: Google Sheets Append

See §7 for column mapping.

#### Node 7: Error Handler

Configured as the "Error Workflow" trigger or as a fallback branch on node 3.
Implements a counter using the execution's static data to track attempt number.

---

## 4. Approval Callback Workflow — Node-by-Node Blueprint

Triggered when a support agent clicks ✅ Approve or ❌ Reject on a Telegram approval message.

```
[1: Telegram Trigger]
        │ on: callback_query (type=callback_query only)
        │ produces: { callback_query_id, data, from.id, from.username }
        │ data format: "approve:{pending_id}" or "reject:{pending_id}"
        ▼
[2: Function — Parse Callback]
        │ splits data on ":" → { decision, pending_id }
        │ sets approved = (decision === "approve")
        │ sets reviewer = String(from.id)
        ▼
[3: HTTP Request — answerCallbackQuery]
        │ URL: https://api.telegram.org/bot{TOKEN}/answerCallbackQuery
        │ Body: { callback_query_id, text: "Processing..." }
        │ ⚠ Must complete within 30 s of button click
        │ Run BEFORE calling /approve (Telegram times out the spinner)
        ▼
[4: HTTP Request — POST /approve]
        │ URL: http://agent:8000/approve
        │ Method: POST
        │ Body: { pending_id, approved, reviewer }
        │ Timeout: 15 000 ms
        │ Do NOT retry on 404 (token expired or already consumed — terminal)
        │ Retry on 5xx: 1 attempt, 10 s delay
        ▼
[5: IF — status == "approved"?]
        │
        ├─── YES ──────────────────────────────────────────────────────┐
        │   [6a: Telegram — Notify Approver]                          │
        │        chat_id: {{ $('2').json.reviewer }}                  │
        │        text: "✅ Action approved. Ticket: {{ $json.result.ticket.ticket_id }}" │
        │                                                              │
        │   [6b: Google Sheets — Update Pending Row to Approved]      │
        │        (match by pending_id; update status, approved_by, ticket_id) │
        │                                                              │
        └─── NO (status == "rejected") ────────────────────────────────┤
            [7a: Telegram — Notify Approver]                          │
                 text: "❌ Action rejected. No ticket created."       │
                                                                       │
            [7b: Google Sheets — Update Pending Row to Rejected]      │
                                                                       │
[8: Error Handler] ◄───────────────────────────────── (on node 4 HTTP 404)
        │ HTTP 404 = token expired or already consumed (terminal, do not retry)
        │ [Telegram — answerCallbackQuery with error text]
        │      text: "⚠ Approval expired or already processed."
        └──────────────────────────────────────────────────────────────
```

### Node 2: Function — Parse Callback

```javascript
const data = $input.item.json.callback_query.data;  // "approve:abc123..."
const [decision, pending_id] = data.split(":");
const from = $input.item.json.callback_query.from;
return [{
  json: {
    pending_id: pending_id,
    approved:   decision === "approve",
    reviewer:   String(from.id)
  }
}];
```

### Node 4: HTTP Request — POST /approve

| Setting | Value |
|---------|-------|
| URL | `{{ $env.AGENT_BASE_URL }}/approve` |
| Method | POST |
| Body | `{ "pending_id": "{{ $json.pending_id }}", "approved": {{ $json.approved }}, "reviewer": "{{ $json.reviewer }}" }` |
| On HTTP 404 | **Stop and handle in error branch** — do not retry |
| On HTTP 5xx | Retry once after 10 s |

---

## 5. Environment Variable Contract

These variables must be configured in n8n before activating workflows.

### n8n Credentials (set under Settings → Credentials)

| Credential name | Type | Value |
|-----------------|------|-------|
| `Telegram Bot API` | Header Auth or Telegram Bot node | `TELEGRAM_BOT_TOKEN` |
| `Agent Webhook Secret` | Header Auth | `WEBHOOK_SECRET` (must match agent `.env`) |
| `Google Sheets` | OAuth2 / Service Account | Service account JSON |

### n8n Environment Variables (set under Settings → Variables)

| Variable | Example value | Notes |
|----------|---------------|-------|
| `AGENT_BASE_URL` | `http://agent:8000` | Agent service URL. Use Docker service name inside `docker-compose`, or public URL in cloud. |
| `TELEGRAM_APPROVAL_CHAT_ID` | `-1001234567890` | Negative group ID or positive private chat ID for the support approval group. |
| `OPS_TELEGRAM_CHAT_ID` | `-1009876543210` | Chat ID for operational alerts (agent unreachable, retries exhausted). |

**Note:** `TELEGRAM_BOT_TOKEN` is set via the Telegram Credential in n8n, not as a plain env var.
The `WEBHOOK_SECRET` must exactly match the value in the agent's `.env` file.

### Agent env vars that n8n reads indirectly (via HTTP response)

n8n does not read these directly but their values affect n8n workflow behaviour:

| Agent env var | Effect on n8n |
|--------------|---------------|
| `APPROVAL_TTL_SECONDS` (default 3600) | n8n Wait node timeout **must be ≤ this value** |
| `APPROVAL_CATEGORIES` | Determines which messages return `status: "pending"` |
| `AUTO_APPROVE_THRESHOLD` | Determines confidence-based pending vs. executed |

---

## 6. Approval State Representation

### State machine

```
             POST /webhook
                  │
       ┌──────────▼──────────┐
       │   risky == false?   │
       └──────────┬──────────┘
                  │ NO                YES
                  │              ┌────▼────────────────┐
                  │              │  pending_created     │
                  │              │  Redis: pending:{id} │
                  │              │  TTL = APPROVAL_TTL  │
                  │              └────┬────────────────┘
                  │                   │ POST /approve (approved=true)
                  │              ┌────▼────────────────┐
       executed ◄─┤              │  pending_approved    │
                  │              │  execute_action()    │
                  │              └────┬────────────────┘
                  │                   │ POST /approve (approved=false)
                  │              ┌────▼────────────────┐
                  │              │  pending_rejected    │
                  │              │  no action taken     │
                  │              └─────────────────────┘
                  │
                  │  TTL expires without /approve call
                  │              ┌──────────────────────┐
                  │              │  pending_expired      │
                  │              │  pop_pending() → None │
                  │              │  → HTTP 404           │
                  │              └──────────────────────┘
```

### How `pending_id` flows through n8n

1. `/webhook` response includes `pending.pending_id` (32-char hex).
2. n8n Triage Workflow encodes it into Telegram inline button `callback_data` as `approve:{pending_id}`.
3. When the user clicks, Telegram sends `callback_query.data = "approve:a1b2..."` to the bot.
4. n8n Approval Callback Workflow parses the `pending_id` and calls `POST /approve` with it.
5. Agent fetches the `PendingDecision` from Redis, executes the action, and deletes the key.

**The `pending_id` is single-use.** A second `POST /approve` call with the same ID returns HTTP 404
(key already deleted). n8n must treat HTTP 404 as terminal — do not retry.

### Expiry alignment

```
APPROVAL_TTL_SECONDS (agent)   ──────────────────────────────────────────────── ⛔ token expires
n8n Wait timeout (if used)     ──────────── ⛔ workflow resumes with timeout
```

Set n8n Wait node timeout to `APPROVAL_TTL_SECONDS - 60 s` to leave a buffer for the HTTP round-trip.

---

## 7. Google Sheets Audit Log

### Sheet structure

Create one sheet with these columns in exact order:

| # | Column | Source | Example |
|---|--------|--------|---------|
| A | `timestamp` | `datetime.now(UTC).isoformat()` | `2026-02-28T10:00:00+00:00` |
| B | `request_id` | `X-Request-ID` header / ContextVar | `a1b2c3d4...` |
| C | `message_id` | `WebhookRequest.message_id` | `tg_12345678` |
| D | `user_id` | SHA-256 hash in production | `d4e5f6a1...` |
| E | `category` | `ClassificationResult.category` | `billing` |
| F | `urgency` | `ClassificationResult.urgency` | `high` |
| G | `confidence` | `ClassificationResult.confidence` | `0.92` |
| H | `action` | `ProposedAction.tool` | `create_ticket_and_reply` |
| I | `status` | Outcome | `executed` / `pending` / `approved` / `rejected` |
| J | `approved_by` | `ApproveRequest.reviewer` or `"auto"` | `support_lead_id` |
| K | `ticket_id` | `action_result.ticket.ticket_id` | `ENG-42` |
| L | `latency_ms` | End-to-end agent latency | `312` |
| M | `cost_usd` | Estimated LLM cost | `0.003` |

### Row write timing

| Event | Row written by |
|-------|---------------|
| Auto-executed | n8n Triage Workflow node 6a |
| Pending (awaiting approval) | n8n Triage Workflow node 5b |
| Approved (action executed) | n8n Approval Callback Workflow node 6b (update existing pending row) |
| Rejected | n8n Approval Callback Workflow node 7b (update existing pending row) |

**Updating vs. appending:** For the approved/rejected case, the preferred approach is to update the
existing "pending" row by matching `pending_id` (store it in column N as a hidden audit field).
This keeps one row per user message regardless of outcome.

---

## 8. Failure Modes & Retries

### 8.1 Agent Unreachable (HTTP 5xx or Timeout)

**n8n behaviour:** Retry chain in Triage Workflow node 7.

| Attempt | Delay | Action |
|---------|-------|--------|
| 1 | 0 s | Initial call |
| 2 | 30 s | Wait → retry |
| 3 | 90 s | Wait → retry |
| Give up | — | Notify ops channel |

**What n8n sends to ops channel:**

```
❌ gdev-agent unreachable after 3 attempts
Execution: {{ $execution.id }}
User: {{ $('1').item.json.message.from.id }}
Error: {{ $json.error.message }}
Time: {{ $now.toISO() }}
```

### 8.2 Invalid Request (HTTP 400)

HTTP 400 from `/webhook` means the message was blocked by the input guard. This is not a transient
failure — **do not retry**. Log to Google Sheets with `status = "guard_blocked"` and optionally
reply to the user with a neutral message ("We couldn't process your message").

### 8.3 Rate Limited (HTTP 429)

**n8n behaviour:** Wait for `Retry-After` header value (or 60 s if absent), then retry once.
If the second attempt also returns 429, notify ops channel.

### 8.4 Approval Token Expired (HTTP 404 on `/approve`)

**n8n behaviour:** This is a terminal condition — the approval window closed.

1. Call `answerCallbackQuery` with text `"⚠ This approval has expired."`.
2. Send a notification to the approver chat.
3. Do **not** retry.

### 8.5 Google Sheets API Quota (HTTP 429)

**n8n behaviour:** Retry with 60 s delay, max 2 attempts. If it still fails, log to n8n execution
log and continue — audit log failure must not block the main flow.

### 8.6 Telegram API Unavailable

**n8n behaviour:** Telegram sends and approval notifications are fire-and-forget. A Telegram 500
does not block ticket creation or the agent response. Log to n8n execution log.

### 8.7 `callback_data` Malformed

**n8n behaviour:** If `data.split(":")` does not produce exactly two parts, or if `pending_id` is
not 32 chars, abort the Approval Callback Workflow and call `answerCallbackQuery` with
`"⚠ Invalid approval request."`.

---

## 9. What Is Configurable in n8n vs. Code

### Configure in n8n (no code change required)

| What | Where in n8n |
|------|-------------|
| Retry count and delays | Node 7 (Error Handler) — Wait node duration |
| Approval message format | Node 5a body template |
| Approval chat group | `TELEGRAM_APPROVAL_CHAT_ID` variable |
| Ops alert chat | `OPS_TELEGRAM_CHAT_ID` variable |
| Google Sheets column order | Sheets append node column mapping |
| Agent base URL | `AGENT_BASE_URL` variable |
| Telegram message filters | Node 1 Trigger settings |

### Configure in agent code / env vars (requires deployment)

| What | Where |
|------|-------|
| Which categories require approval | `APPROVAL_CATEGORIES` env var |
| Confidence threshold for auto-approval | `AUTO_APPROVE_THRESHOLD` env var |
| Approval token TTL | `APPROVAL_TTL_SECONDS` env var |
| Injection guard patterns | `INJECTION_PATTERNS` in `app/agent.py` |
| URL allowlist for output guard | `URL_ALLOWLIST` env var |
| Rate limit per user | `RATE_LIMIT_RPM` env var |
| LLM model selection | `ANTHROPIC_MODEL` env var |

### Never change at runtime (requires code PR)

| What | Reason |
|------|--------|
| Tool registry dispatch logic | Requires test coverage and PR review |
| LLM tool schemas (`TOOLS` in `llm_client.py`) | Changing schema changes model behaviour — needs eval run |
| HTTP endpoint paths (`/webhook`, `/approve`) | n8n workflows must stay in sync |
| `pending_id` format (32-char hex) | Breaking change for in-flight approvals |

---

## 10. Local Development Setup

```bash
# 1. Start the stack
docker compose up --build

# 2. Import workflows
#    In n8n UI (localhost:5678):
#    → Settings → Workflows → Import from file
#    → Select n8n/workflow_triage.json
#    → Select n8n/workflow_approval_callback.json

# 3. Set credentials
#    → Settings → Credentials → New → Telegram Bot API
#       API Key: your TELEGRAM_BOT_TOKEN
#    → Settings → Credentials → New → Header Auth (for webhook signature)
#       Name: X-Webhook-Signature
#       Value: sha256=... (computed by n8n expression)

# 4. Set variables
#    → Settings → Variables:
#       AGENT_BASE_URL = http://agent:8000
#       TELEGRAM_APPROVAL_CHAT_ID = -1001234567890
#       OPS_TELEGRAM_CHAT_ID = -1009876543210

# 5. Activate both workflows

# 6. Verify
curl http://localhost:8000/health
# {"status": "ok", "app": "gdev-agent"}
```

### Testing without Telegram

Send a request directly to the agent, bypassing n8n:

```bash
# Auto-executed (gameplay question)
curl -s -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -d '{"user_id":"u1","text":"How do I unlock the third world?"}' | jq .status
# "executed"

# Pending approval (billing)
PENDING_ID=$(curl -s -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -d '{"user_id":"u2","text":"Charged twice for crystals, TXN-5512"}' \
  | jq -r '.pending.pending_id')

# Approve
curl -s -X POST http://localhost:8000/approve \
  -H "Content-Type: application/json" \
  -d "{\"pending_id\":\"$PENDING_ID\",\"approved\":true,\"reviewer\":\"dev\"}" | jq .status
# "approved"
```
