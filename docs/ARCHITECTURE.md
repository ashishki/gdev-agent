# gdev-agent — Architecture

_Last updated: 2026-02-28 · Reflects current codebase + agreed hardening plan from `docs/REVIEW_NOTES.md`_

---

## 1. Use Case: Player Support Triage

Every game studio handles a continuous stream of player requests — bugs, billing disputes, account issues, cheater reports.
Manual sorting causes SLA delays and missed tickets.
This agent adds concrete value by understanding free-form text, extracting structure, routing to the right team, and drafting a reply — while keeping humans in the loop for high-risk cases.

**Input channels (MVP):** Telegram bot webhook or any HTTP POST from n8n/Make.

**Measurable outcomes:** classification accuracy, ticket creation latency, approval rate, cost per request.

---

## 2. Current Architecture

### 2.1 Component Status

| Component | Module / File | Status |
|-----------|--------------|--------|
| FastAPI entrypoint | `app/main.py` | Implemented |
| Settings | `app/config.py` | Implemented |
| Request / response schemas | `app/schemas.py` | Implemented |
| Agent orchestration | `app/agent.py` | Implemented (rule-based; LLM loop pending — see §3) |
| JSON structured logger | `app/logging.py` | Implemented (partial — see Hardening Plan) |
| Pending approval store | `app/store.py` | Implemented (in-memory + optional SQLite; Redis pending) |
| Ticketing integration | `app/tools/ticketing.py` | Stub — returns fake `TKT-*` ID |
| Messaging integration | `app/tools/messenger.py` | Stub — returns `"queued"` |
| Eval harness | `eval/runner.py` | Implemented |
| Eval dataset | `eval/cases.jsonl` | 6 cases (expand to 25 — see Hardening Plan) |
| n8n workflow | _(not yet committed)_ | Planned |
| Redis dedup / approval | _(not yet)_ | Planned |
| Linear integration | _(not yet)_ | Planned |
| Telegram integration | _(not yet)_ | Planned |
| Google Sheets audit log | _(not yet)_ | Planned |

### 2.2 Repository Layout

```
gdev-agent/
├── app/
│   ├── main.py          # FastAPI app, lifespan, endpoint wiring
│   ├── config.py        # pydantic-settings; loaded once via get_settings()
│   ├── schemas.py       # All Pydantic request/response/internal models
│   ├── agent.py         # AgentService: classify, extract, propose, approve
│   ├── logging.py       # JsonFormatter + configure_logging()
│   ├── store.py         # EventStore: pending dict + SQLite event log
│   └── tools/
│       ├── __init__.py
│       ├── ticketing.py # create_ticket() stub
│       └── messenger.py # send_reply() stub
├── eval/
│   ├── runner.py        # run_eval() — accuracy + per-label breakdown
│   └── cases.jsonl      # JSONL test cases
├── docs/
│   ├── ARCHITECTURE.md  # this file
│   ├── PLAN.md
│   └── REVIEW_NOTES.md
└── .env.example
```

### 2.3 Request Data Flow

```
Telegram / n8n / HTTP client
        │
        │  POST /webhook  {message_id, user_id, text, metadata}
        ▼
app/main.py  →  AgentService.process_webhook()
        │
        ├── _guard_input()          app/agent.py
        │     length check, injection pattern match
        │     → ValueError  →  HTTP 400
        │
        ├── classify_request()      app/agent.py
        │     [rule-based now; replaced by llm_client.run_agent() in C-1]
        │     → ClassificationResult {category, urgency, confidence}
        │
        ├── extract_fields()        app/agent.py
        │     regex: TXN-*, E-*, platform tokens
        │     → ExtractedFields {platform, transaction_id, error_code, keywords}
        │
        ├── propose_action()        app/agent.py
        │     builds ProposedAction; sets risky=True + risk_reason
        │     when: approval_categories | urgency high/critical |
        │           confidence < auto_approve_threshold | legal keywords
        │
        └── needs_approval()?
              YES → store.put_pending()  →  HTTP 200  {status:"pending", pending_id}
              NO  → execute_action()
                      create_ticket()   app/tools/ticketing.py
                      send_reply()      app/tools/messenger.py
                      store.log_event()
                    → HTTP 200  {status:"executed", action_result}
```

```
n8n / approver
        │
        │  POST /approve  {pending_id, approved, reviewer}
        ▼
AgentService.approve()
        │
        ├── store.pop_pending(pending_id)
        │     → None → HTTP 404          ← (fix C-2; currently returns 200)
        │
        ├── approved=False → log "rejected" → HTTP 200 {status:"rejected"}
        │
        └── approved=True  → execute_action(pending.action, pending.user_id, ...)
                              → HTTP 200 {status:"approved", result}
```

---

## 3. LLM Integration (Target State — fix C-1)

The classifier and extractor will be replaced by a Claude `tool_use` loop.
The implementation lives in `app/llm_client.py` (to be created).

### Tool Schema

```python
TOOLS = [
    {
        "name": "classify_request",
        "description": "Classifies support request into category and sets urgency",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["bug_report", "billing", "account_access",
                             "cheater_report", "gameplay_question", "other"]
                },
                "urgency":    {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1}
            },
            "required": ["category", "urgency", "confidence"]
        }
    },
    {
        "name": "extract_entities",
        "description": "Extracts structured entities from the message",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id":           {"type": "string"},
                "platform":          {"type": "string", "enum": ["iOS", "Android", "PC", "PS5", "Xbox", "unknown"]},
                "game_title":        {"type": "string"},
                "transaction_id":    {"type": "string"},
                "error_code":        {"type": "string"},
                "reported_username": {"type": "string"}
            }
        }
    },
    {
        "name": "lookup_faq",
        "description": "Looks up top-3 relevant KB articles by keywords",
        "input_schema": {
            "type": "object",
            "properties": {
                "keywords": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["keywords"]
        }
    },
    {
        "name": "draft_reply",
        "description": "Drafts a polite, helpful reply to the user",
        "input_schema": {
            "type": "object",
            "properties": {
                "tone":             {"type": "string", "enum": ["empathetic", "informational", "escalation"]},
                "include_faq_links": {"type": "boolean"},
                "draft_text":       {"type": "string"}
            },
            "required": ["tone", "draft_text"]
        }
    },
    {
        "name": "flag_for_human",
        "description": "Flags request for mandatory human review before any action",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason":     {"type": "string"},
                "risk_level": {"type": "string", "enum": ["medium", "high", "critical"]}
            },
            "required": ["reason", "risk_level"]
        }
    }
]
```

### Tool Loop (`app/llm_client.py`)

```
build_messages(request) → List[Message]
    │
    ▼
client.messages.create(model, tools=TOOLS, tool_choice="auto")
    │
    loop (max_turns = 5):
    │   stop_reason == "end_turn"  → break
    │   stop_reason == "tool_use"  → dispatch tool call → append tool_result
    │
    ▼
return TriageResult assembled from tool outputs
```

Model is read from `Settings.anthropic_model` (env: `ANTHROPIC_MODEL`, default `claude-sonnet-4-6`).

---

## 4. Approval Flow

```
Agent calls propose_action() with risky=True
        │
        ▼
store.put_pending(PendingDecision)   ← stores user_id, action, draft, expires_at
        │
        ▼
/webhook returns {status:"pending", pending_id, draft_response}
        │
        ▼
n8n / Telegram sends approval message to support team
        │
        ├── Approve → POST /approve {pending_id, approved:true, reviewer}
        │               execute_action() → ticket created → reply sent
        │
        └── Reject  → POST /approve {pending_id, approved:false, reviewer}
                        log_event("pending_rejected") → no ticket
```

**Approval trigger criteria** (all evaluated in `propose_action()` — see fix M-1):

| Condition | `risk_reason` set |
|-----------|-------------------|
| `category` in `APPROVAL_CATEGORIES` env var | yes |
| `urgency` in `{"high", "critical"}` | yes |
| `confidence` < `AUTO_APPROVE_THRESHOLD` | yes |
| Legal keywords: `lawyer`, `lawsuit`, `press`, `gdpr` | yes |

Pending approvals expire after `APPROVAL_TTL_SECONDS` (default 3600).
Expired entries are evicted on lookup in `store.pop_pending()`.

---

## 5. API Contract

### `POST /webhook`

**Request:**
```json
{
  "message_id": "tg_12345678",
  "user_id": "user_abc123",
  "text": "I bought crystals but they never arrived, TXN-9981",
  "metadata": {"chat_id": "123456", "username": "player_nick"}
}
```

**Response — auto-executed (HTTP 200):**
```json
{
  "status": "executed",
  "classification": {"category": "billing", "urgency": "high", "confidence": 0.92},
  "extracted": {"transaction_id": "TXN-9981", "platform": "unknown"},
  "action": {"tool": "create_ticket_and_reply", "risky": false},
  "draft_response": "Thanks for reporting this payment issue...",
  "action_result": {"ticket": {"ticket_id": "TKT-A1B2C3D4"}, "reply": {"delivery": "queued"}}
}
```

**Response — pending approval (HTTP 200):**
```json
{
  "status": "pending",
  "classification": {"category": "billing", "urgency": "high", "confidence": 0.92},
  "action": {"tool": "create_ticket_and_reply", "risky": true, "risk_reason": "category 'billing' requires approval"},
  "draft_response": "...",
  "pending": {"pending_id": "abc123hex", "reason": "category 'billing' requires approval"}
}
```

**Errors:**
```json
{"detail": "Input exceeds max length (2000)"}          // HTTP 400
{"detail": "Input failed injection guard"}             // HTTP 400
```

### `POST /approve`

**Request:**
```json
{"pending_id": "abc123hex", "approved": true, "reviewer": "support_lead_id"}
```

**Response (HTTP 200):**
```json
{"status": "approved", "pending_id": "abc123hex", "result": {"ticket": {...}, "reply": {...}}}
```

**Not found (HTTP 404):**  ← target state after fix C-2
```json
{"detail": "pending_id not found"}
```

### `GET /health`

```json
{"status": "ok", "app": "gdev-agent"}
```

---

## 6. Security & Safety

### Input Guard (`app/agent.py · _guard_input()`)

Runs before any classification. Raises `ValueError` → HTTP 400 on failure.

| Check | Detail |
|-------|--------|
| Length | `len(text) > MAX_INPUT_LENGTH` (default 2000) |
| Injection patterns | Checked case-insensitively on lowercased text. See full pattern list in `INJECTION_PATTERNS` constant. Covers: `"ignore previous instructions"`, `"system:"`, `"[inst]"`, `"[/inst]"`, `"act as"`, `"you are now"`, `"forget all"`, `"disregard"`, `"developer mode"`, `"jailbreak"`, `"<\|system\|>"`, `"[system]"` |

**Note:** Input guard runs before the LLM call. It is a fast-path block, not a substitute for output-side validation.

### Output Guard (planned)

After LLM integration (C-1), add `_guard_output()` in `app/agent.py`:
- Regex scan for secret patterns (`sk-ant-`, `lin_api_`, bearer tokens).
- URL allowlist — reject any URL not on an explicit allow list before returning draft text.
- Confidence gate — if `confidence < 0.5`, force `flag_for_human` regardless of category.

### Approval Gate

All `billing` and `account_access` requests require human approval by default (configurable via `APPROVAL_CATEGORIES`).
High/critical urgency always requires approval.
The `pending_id` is a 128-bit random hex token (`uuid4().hex`) — not guessable by brute force.
`reviewer` field in `ApproveRequest` is logged for audit; authentication of the reviewer identity is delegated to the calling orchestrator (n8n with Telegram inline buttons).

### Secrets

```
.env (never commit):
  ANTHROPIC_API_KEY=sk-ant-...
  LINEAR_API_KEY=lin_api_...
  TELEGRAM_BOT_TOKEN=...
  TELEGRAM_APPROVAL_CHAT_ID=...

Production: Docker secrets / AWS Secrets Manager
```

`.gitignore` must include: `.env`, `*.key`, `secrets/`.
No secret material is interpolated into log lines.
`user_id` values are passed through as-is in MVP; production logging should hash them (`sha256(user_id)`).

---

## 7. Observability

### Log Format

Every log line from `app/logging.py · JsonFormatter` is a JSON object:

```json
{
  "timestamp": "2026-02-28T10:00:00.123456+00:00",
  "level": "INFO",
  "logger": "app.agent",
  "message": "action executed",
  "request_id": "a1b2c3d4e5f6...",
  "event": "action_executed",
  "context": {
    "pending_id": "...",
    "category": "billing",
    "latency_ms": 312
  }
}
```

`timestamp` is derived from `record.created` (event time), not serialization time — see fix M-5.

### Request Correlation

A FastAPI middleware in `app/main.py` reads `X-Request-ID` from the incoming request (or generates `uuid4().hex` if absent).
The value is stored in a `ContextVar[str]` defined in `app/logging.py` and injected into every log line by `JsonFormatter`.
The same ID is echoed in the response `X-Request-ID` header.
This allows all log lines from a single request to be grouped in any log aggregator.

### Event Types (SQLite log / stdout)

| `event_type` | Emitted when |
|---|---|
| `pending_created` | Action sent for human approval |
| `pending_resolved` | Approval store entry fetched (approve or reject) |
| `pending_approved` | Human approved; action executed |
| `pending_rejected` | Human rejected; no action taken |
| `action_executed` | Auto-executed without approval |

### Error Taxonomy (HTTP responses)

| Scenario | HTTP status | `detail` |
|---|---|---|
| Input too long | 400 | `"Input exceeds max length (N)"` |
| Injection pattern detected | 400 | `"Input failed injection guard"` |
| `pending_id` not found or expired | 404 | `"pending_id not found"` |
| Unhandled exception | 500 | FastAPI default |

---

## 8. Extensibility

### Adding a New Tool

1. **Write the handler** in `app/tools/<name>.py` as a plain function:
   ```python
   def my_tool(payload: dict[str, Any]) -> dict[str, Any]: ...
   ```
2. **Register it** in the tool registry dict in `app/tools/__init__.py`:
   ```python
   TOOL_REGISTRY: dict[str, Callable] = {
       "create_ticket_and_reply": _create_ticket_and_reply,
       "my_tool": my_tool,
   }
   ```
3. **Add the tool schema** to `TOOLS` in `app/llm_client.py` (once C-1 is implemented).
4. `AgentService.execute_action()` dispatches by `action.tool` key — no changes needed there.

No modifications to `agent.py`, `main.py`, or `schemas.py` are required for a new tool.

### Adding a New Category

1. Add the string to the `Category` `Literal` in `app/schemas.py`.
2. Add a draft reply branch in `AgentService._draft_response()` in `app/agent.py`.
3. Add a tool schema enum value to `classify_request.input_schema` in `app/llm_client.py`.
4. Add eval cases for the new category to `eval/cases.jsonl`.

### Adding a New Input Channel

The `/webhook` endpoint accepts any `WebhookRequest` payload.
Adding a new channel (email, Slack) requires only:
- A new n8n node (or a thin adapter) that normalises the channel's payload into `WebhookRequest` fields.
- No changes to the agent service itself.

---

## 9. Environment Variables

```bash
# App
APP_NAME=gdev-agent
APP_ENV=dev                          # dev | staging | prod
LOG_LEVEL=INFO

# LLM (required when C-1 is implemented)
ANTHROPIC_API_KEY=                   # sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-6

# Agent behaviour
MAX_INPUT_LENGTH=2000
AUTO_APPROVE_THRESHOLD=0.85          # confidence above this → auto-approve (low/medium only)
APPROVAL_CATEGORIES=billing,account_access
APPROVAL_TTL_SECONDS=3600            # pending entries expire after this many seconds

# Storage
SQLITE_LOG_PATH=                     # optional; empty disables SQLite event log

# Integrations (planned)
LINEAR_API_KEY=
LINEAR_TEAM_ID=
TELEGRAM_BOT_TOKEN=
TELEGRAM_APPROVAL_CHAT_ID=
GOOGLE_SHEETS_CREDENTIALS_JSON=      # path to service account JSON
GOOGLE_SHEETS_ID=
REDIS_URL=redis://redis:6379
```

---

## 10. Hardening Plan

Summary of agreed fixes from `docs/REVIEW_NOTES.md`.
Each item references the finding ID and lists affected files.

### Pass 1 — Low risk, no new dependencies

| ID | Fix | Files |
|----|-----|-------|
| C-2 | Return HTTP 404 (not 200) when `pending_id` not found | `app/main.py`, `app/agent.py`, `app/schemas.py` |
| C-3 | Store `user_id` in `PendingDecision`; pass it to `execute_action()` on approval | `app/schemas.py`, `app/agent.py` |
| C-4 | Add `expires_at` to `PendingDecision`; evict expired entries in `pop_pending()` | `app/schemas.py`, `app/store.py`, `app/config.py` |
| C-5 | Execute `PRAGMA journal_mode=WAL` after SQLite connect | `app/store.py` |
| M-1 | Move legal-keyword check into `propose_action()`; reduce `needs_approval()` to `return action.risky` | `app/agent.py` |
| M-2 | Extend `INJECTION_PATTERNS` to cover common jailbreak prefixes | `app/agent.py` |
| M-5 | Use `record.created` for log timestamp instead of `datetime.now()` | `app/logging.py` |
| N-1 | Set `ensure_ascii=False` in `json.dumps` calls | `app/logging.py`, `app/store.py` |

### Pass 2 — Structural / requires validation

| ID | Fix | Files |
|----|-----|-------|
| C-1 | Implement Claude `tool_use` loop in `app/llm_client.py`; replace keyword classifier | `app/llm_client.py` (new), `app/agent.py`, `app/config.py`, `.env.example` |
| M-3 | Move `configure_logging()` into FastAPI lifespan or startup handler | `app/main.py`, `app/logging.py` |
| M-4 | Add `ContextVar` + middleware for `X-Request-ID` propagation | `app/main.py`, `app/logging.py` |
| M-6 | Tighten error-code regex to require minimum digit count or known prefix | `app/agent.py` |
| N-3 | Replace hardcoded dispatch in `execute_action()` with `TOOL_REGISTRY` dict | `app/agent.py`, `app/tools/__init__.py` |
| N-4 | Measure and log `latency_ms` per request | `app/agent.py` or `app/main.py` |
| N-5 | Expand `eval/cases.jsonl` to 25 cases; track guard-blocked cases separately in runner | `eval/cases.jsonl`, `eval/runner.py` |
