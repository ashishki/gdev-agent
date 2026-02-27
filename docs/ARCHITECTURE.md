# gdev-agent — Architecture

## 1. Selected Use Case: Player Support Triage

**Why this one:**
- Every game studio handles a stream of incoming player requests (bugs, billing, account issues, cheater reports).
- Manual sorting wastes time, causes SLA delays, and leads to missed tickets.
- LLM adds concrete value here: understands free-form text, extracts structure, routes to the right team, drafts a reply.
- Easy to measure: classification accuracy, response time, ticket count.
- Demo fits in 5 minutes: show an incoming message → agent classifies → creates a ticket in Linear → sends reply via Telegram.

**Input channels (MVP):** Telegram bot (webhook) or email (forwarding → webhook).

---

## 2. Architecture Components

```
┌─────────────────────────────────────────────────────────┐
│                     INPUT CHANNEL                        │
│   Telegram Bot / Email webhook → n8n HTTP trigger       │
└──────────────────────┬──────────────────────────────────┘
                       │ POST /triage
                       ▼
┌─────────────────────────────────────────────────────────┐
│                   n8n ORCHESTRATOR                       │
│  1. Dedup (Redis TTL check by message_id)                │
│  2. Rate limit guard                                     │
│  3. Call Agent API → parse response                      │
│  4. Risk check: auto vs. approval branch                 │
│  5. On approval: create ticket + send reply              │
│  6. Log result to Google Sheets / Postgres               │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│                  AGENT SERVICE (Python/FastAPI)          │
│                                                          │
│  POST /triage                                            │
│    ├── GuardInput (PII check, length, injection guard)   │
│    ├── Claude claude-sonnet-4-6 (tool_use mode)               │
│    │     Tools:                                          │
│    │       - classify_request()    → category + confidence│
│    │       - extract_entities()    → user_id, platform,  │
│    │                                  game, severity     │
│    │       - lookup_faq()          → top-3 KB articles   │
│    │       - draft_reply()         → suggested response  │
│    │       - flag_for_human()      → triggers approval   │
│    ├── GuardOutput (no secrets, no harmful content)      │
│    └── Return TriageResult JSON                          │
│                                                          │
│  POST /approve  (called by n8n after human approves)     │
│    └── create_ticket(payload) → Linear/Jira API          │
└──────────────────────┬──────────────────────────────────┘
                       │
           ┌───────────┼───────────┐
           ▼           ▼           ▼
      Linear API   Telegram    Google Sheets
      (tickets)    Bot API     (audit log)
                   (replies)
```

### Component Table

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Orchestrator | n8n (self-hosted docker) | Triggers, retries, routing, approval flow |
| Agent Service | Python 3.11 + FastAPI | LLM logic, tool calling, guardrails |
| LLM | Claude claude-sonnet-4-6 (Anthropic API) | Classification, extraction, reply drafting |
| Ticket Tracker | Linear (REST API) | Create/update issues |
| Notification | Telegram Bot API | Reply to user + approval messages to team |
| Audit Log | Google Sheets (Sheets API) | Log all decisions + eval dataset |
| Dedup Cache | Redis (TTL 24h) | Prevent duplicate processing |
| Secrets | `.env` + docker secrets | API keys |

---

## 3. Tool Calling Schema

The agent runs in `tool_use` mode (Anthropic SDK). Each tool is a Python function with a JSON Schema definition.

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
                "urgency": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
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
                "user_id": {"type": "string"},
                "platform": {"type": "string", "enum": ["iOS", "Android", "PC", "PS5", "Xbox", "unknown"]},
                "game_title": {"type": "string"},
                "transaction_id": {"type": "string"},
                "error_code": {"type": "string"},
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
                "tone": {"type": "string", "enum": ["empathetic", "informational", "escalation"]},
                "include_faq_links": {"type": "boolean"},
                "draft_text": {"type": "string"}
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
                "reason": {"type": "string"},
                "risk_level": {"type": "string", "enum": ["medium", "high", "critical"]}
            },
            "required": ["reason", "risk_level"]
        }
    }
]
```

---

## 4. Approval Flow (Human-in-the-Loop)

```
Agent calls flag_for_human()
    │
    ▼
n8n sends a Telegram message to the support team:
  "New ticket requires approval:
   [category] [urgency] [text preview]
   ✅ Approve  ❌ Reject  📝 Edit"
    │
    ├── ✅ Approve → n8n calls POST /approve → creates ticket → replies to user
    ├── ❌ Reject  → log, skip ticket creation, notify user
    └── 📝 Edit    → opens reply editing form
```

**Approval trigger criteria:**
- urgency = `critical` or `high`
- category = `billing` (any transaction)
- confidence < 0.6 (agent is uncertain)
- Legal/PR risk keywords detected in the message

---

## 5. Guardrails

### Input Guard
```python
def guard_input(text: str) -> GuardResult:
    # 1. Length: max 2000 chars
    # 2. Language detect (ru/en only for MVP)
    # 3. Basic prompt injection patterns:
    #    "ignore previous instructions", "system:", "[INST]"
    # 4. PII: do not log raw text (hash user_id)
```

### Output Guard
```python
def guard_output(response: str) -> GuardResult:
    # 1. No API keys / secrets in output (regex scan)
    # 2. No URLs outside the allowlist
    # 3. Confidence threshold: if < 0.5 → force flag_for_human
```

---

## 6. Secrets Management

```
.env (never commit):
  ANTHROPIC_API_KEY=sk-ant-...
  LINEAR_API_KEY=lin_api_...
  TELEGRAM_BOT_TOKEN=...
  TELEGRAM_APPROVAL_CHAT_ID=...
  GOOGLE_SHEETS_ID=...
  REDIS_URL=redis://localhost:6379

docker-compose: env_file: .env
Production: Docker secrets / AWS Secrets Manager
```

`.gitignore` must include: `.env`, `*.key`, `secrets/`

---

## 7. Logging

Every request is logged to Google Sheets + stdout (JSON):

```json
{
  "request_id": "uuid4",
  "timestamp": "2026-02-27T10:00:00Z",
  "message_hash": "sha256(raw_text)",
  "channel": "telegram",
  "category": "billing",
  "urgency": "high",
  "confidence": 0.87,
  "tools_called": ["classify_request", "extract_entities", "draft_reply"],
  "approved": true,
  "approved_by": "human|auto",
  "ticket_id": "LIN-1234",
  "latency_ms": 1240,
  "input_tokens": 312,
  "output_tokens": 189,
  "total_cost_usd": 0.0021
}
```

---

## 8. API Contract

### POST /triage

**Request:**
```json
{
  "message_id": "tg_12345678",
  "channel": "telegram",
  "user_id": "user_abc123",
  "text": "I bought crystals but they never arrived, transaction TXN-9981",
  "attachments": [],
  "metadata": {
    "chat_id": "123456",
    "username": "player_nick"
  }
}
```

**Response 200 (requires approval):**
```json
{
  "request_id": "uuid4",
  "classification": {
    "category": "billing",
    "urgency": "high",
    "confidence": 0.92
  },
  "entities": {
    "transaction_id": "TXN-9981",
    "platform": "unknown",
    "game_title": null
  },
  "suggested_reply": "Hello! We've logged your issue with transaction TXN-9981...",
  "faq_articles": ["billing-faq-01", "purchase-issues-02"],
  "action": {
    "type": "requires_approval",
    "reason": "billing category with transaction_id",
    "auto_ticket": false
  },
  "approval_token": "appr_uuid4"
}
```

**Response 200 (auto-resolved):**
```json
{
  "...": "...",
  "action": {
    "type": "auto_resolved",
    "ticket_id": "LIN-1234",
    "ticket_url": "https://linear.app/gdev/issue/LIN-1234"
  }
}
```

**Errors:**
```json
{ "error": "rate_limited", "retry_after": 60 }
{ "error": "input_guard_failed", "detail": "prompt_injection_detected" }
{ "error": "llm_timeout", "detail": "upstream timeout after 30s" }
```

### POST /approve

**Request:**
```json
{
  "approval_token": "appr_uuid4",
  "decision": "approve",
  "editor_note": "",
  "approved_by": "support_lead_id"
}
```

**Response 200:**
```json
{
  "ticket_id": "LIN-1235",
  "ticket_url": "https://linear.app/gdev/issue/LIN-1235",
  "reply_sent": true
}
```

### GET /health
```json
{ "status": "ok", "version": "0.1.0", "llm_reachable": true }
```

---

## 9. Environment Variables

```bash
# LLM
ANTHROPIC_API_KEY=               # required
ANTHROPIC_MODEL=claude-sonnet-4-6     # default

# Ticket Tracker
LINEAR_API_KEY=                  # required
LINEAR_TEAM_ID=                  # required (Linear team ID)

# Telegram
TELEGRAM_BOT_TOKEN=              # required
TELEGRAM_APPROVAL_CHAT_ID=       # required (approval group chat)

# Google Sheets
GOOGLE_SHEETS_CREDENTIALS_JSON=  # path to service account json
GOOGLE_SHEETS_ID=                # spreadsheet ID

# Infrastructure
REDIS_URL=redis://redis:6379
LOG_LEVEL=INFO
AGENT_PORT=8000
MAX_INPUT_LENGTH=2000
AUTO_APPROVE_THRESHOLD=0.85      # confidence above this → auto-approve (low/medium urgency only)
REQUIRE_APPROVAL_CATEGORIES=billing,account_access
```
