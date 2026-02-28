# Codex Agent Prompt — gdev-agent Implementation

> **Role:** You are a staff-level backend engineer implementing a production FastAPI service.
> Work strictly within the contracts defined in this file and the referenced docs.
> Do not add features beyond what is specified. Do not change endpoint paths or response schemas.

---

## 0. Repository Context

You are working in the `gdev-agent` repository — an AI-powered triage service for game-studio
player support. The service accepts player messages via `POST /webhook`, classifies them with
Claude `tool_use`, and either auto-executes an action or routes the message to a human approver.

**Read these docs before writing any code (all are committed):**

| File | Purpose |
|------|---------|
| `docs/ARCHITECTURE.md` | Full system design: API contracts, data models, security model, observability, extensibility |
| `docs/PLAN.md` | PR-by-PR implementation plan with acceptance criteria, risks, and backout plans |
| `docs/REVIEW_NOTES.md` | Engineering review checklist — apply before every PR |
| `docs/N8N.md` | n8n workflow blueprint and Google Sheets audit log schema |

**Existing implemented code (do not rewrite, only extend):**

| Module | Purpose |
|--------|---------|
| `app/main.py` | FastAPI app, lifespan, request-id middleware, `/webhook` and `/approve` endpoints |
| `app/config.py` | `pydantic-settings` settings; loaded via `get_settings()` |
| `app/schemas.py` | All Pydantic models: `WebhookRequest`, `WebhookResponse`, `PendingDecision`, `ProposedAction` |
| `app/agent.py` | `AgentService`: `process_webhook()`, `approve()`, `_guard_input()`, `propose_action()`, `execute_action()` |
| `app/llm_client.py` | `LLMClient`: Claude `tool_use` loop → `TriageResult` |
| `app/logging.py` | `JsonFormatter`, `REQUEST_ID` ContextVar |
| `app/store.py` | `EventStore`: in-memory pending dict + optional SQLite event log |
| `app/tools/ticketing.py` | `create_ticket()` stub |
| `app/tools/messenger.py` | `send_reply()` stub |
| `eval/runner.py` | Eval harness |
| `eval/cases.jsonl` | 6 labelled eval cases |
| `tests/test_approval_flow.py` | Approval flow tests |
| `tests/test_guardrails_and_extraction.py` | Guard and extraction tests |

---

## 1. Implementation Order

Implement PRs in this exact order. Each PR is a self-contained git commit.

```
PR-3 → PR-2 → PR-1 → PR-7 → PR-5 → PR-6 → PR-4 (skip — n8n JSON already committed) → PR-8 → PR-9 → PR-10
```

PR-3 is a pure refactor (zero risk). PR-2 and PR-1 are safety-critical. Do not skip steps.

---

## 2. PR-3 — Tool Registry [P0]

**Goal:** Replace hardcoded `if action.tool ==` dispatch in `execute_action()` with a dict-based
`TOOL_REGISTRY`. New tools must be addable by writing one handler + one registry entry, with no
changes to `agent.py`, `main.py`, or `schemas.py`.

**Files to create/modify:**

- `app/tools/__init__.py` — define `TOOL_REGISTRY`
- `app/agent.py` — update `execute_action()` to use `TOOL_REGISTRY`

**Handler type signature (enforce with a `TypeAlias`):**

```python
from typing import Any, Callable
ToolHandler = Callable[[dict[str, Any], str | None], dict[str, Any]]

TOOL_REGISTRY: dict[str, ToolHandler] = {
    "create_ticket_and_reply": _create_ticket_and_reply,
}
```

The `_create_ticket_and_reply` wrapper calls the existing stubs in `ticketing.py` and
`messenger.py`. Do not change the stub signatures.

**`execute_action()` updated logic:**

```python
handler = TOOL_REGISTRY.get(action.tool)
if handler is None:
    raise ValueError(f"Unknown tool: {action.tool!r}")
return handler(action.payload, user_id)
```

**Acceptance criteria:**
1. `execute_action()` contains no `if action.tool ==` branches.
2. Calling with an unknown `action.tool` raises `ValueError`.
3. All existing tests pass without modification.
4. CI check: `grep -r "action\.tool ==" app/agent.py` returns no matches.

**Tests:** `tests/test_tool_registry.py`
- Known tool dispatches correctly.
- Unknown tool raises `ValueError`.
- `TOOL_REGISTRY` type annotation is `dict[str, ToolHandler]`.

---

## 3. PR-2 — Output Guard [P0]

**Goal:** Add `_guard_output()` to `AgentService` that scans LLM draft text for leaked secrets
and disallowed URLs, and enforces a hard confidence floor.

**Files to create:**

- `app/guardrails/__init__.py` — empty
- `app/guardrails/output_guard.py` — `OutputGuard` class

**`OutputGuard.scan()` signature:**

```python
@dataclass
class GuardResult:
    blocked: bool           # True = HTTP 500, do not return draft
    redacted_draft: str     # draft with disallowed URLs stripped (if OUTPUT_URL_BEHAVIOR=strip)
    reason: str | None      # logged, never sent to client

class OutputGuard:
    def scan(
        self,
        draft: str,
        confidence: float,
        action: ProposedAction,
    ) -> GuardResult: ...
```

**Secret patterns (compile at module load, not per-call):**

```python
import re
_SECRET_PATTERNS = [
    re.compile(r'sk-ant-[a-zA-Z0-9\-]{20,}'),
    re.compile(r'lin_api_[a-zA-Z0-9]{20,}'),
    re.compile(r'Bearer\s+[a-zA-Z0-9+/=]{20,}'),
]
```

**URL allowlist behaviour:**
- Extract all URLs from `draft` using `re.findall(r'https?://[^\s\'"<>]+', draft)`.
- For each URL, parse the host with `urllib.parse.urlparse`.
- If host is not in `settings.url_allowlist`:
  - `OUTPUT_URL_BEHAVIOR=strip`: remove the URL from draft, log `output_guard_redacted`.
  - `OUTPUT_URL_BEHAVIOR=reject`: return `GuardResult(blocked=True)`.

**Confidence floor:**
- If `confidence < 0.5`: override `action.tool = "flag_for_human"`, `action.risky = True`,
  `action.risk_reason = "confidence below safety floor"`. Do NOT block — let it proceed to
  the pending approval path.

**Integration in `agent.py`:**
- Call `OutputGuard.scan()` after `llm_client.run_agent()` returns, before `needs_approval` check.
- If `guard_result.blocked`: raise `HTTPException(500, detail="Internal: output guard blocked response")`.
- Otherwise use `guard_result.redacted_draft` as the draft going forward.

**New config vars (add to `app/config.py` and `.env.example`):**

```python
output_guard_enabled: bool = True
url_allowlist: list[str] = []          # comma-separated in env: URL_ALLOWLIST=kb.example.com
output_url_behavior: Literal["strip", "reject"] = "strip"
```

**Acceptance criteria:**
1. Draft containing `sk-ant-aBcD1234567890abcde` → HTTP 500, detail does not include the secret.
2. Draft containing `lin_api_XyZ1234567890abcde` → HTTP 500.
3. URL not in allowlist + `strip` → URL removed from draft, `output_guard_redacted` logged.
4. URL in allowlist → passes unchanged.
5. `confidence=0.3` → action overridden to `flag_for_human`, `risky=True`.
6. `OUTPUT_GUARD_ENABLED=false` → all checks skip.

**Tests:** `tests/test_output_guard.py` — each secret pattern; URL strip/pass; confidence 0.3, 0.5, 0.85; guard disabled.

---

## 4. PR-1 — Redis Approval Store + Idempotency Dedup [P0]

**Goal:** Replace in-memory pending dict with Redis. Add `message_id`-based dedup so duplicate
`POST /webhook` calls return the cached response without reprocessing.

**Files to create:**

- `app/approval_store.py` — `RedisApprovalStore`
- `app/dedup.py` — `DedupCache`

**`RedisApprovalStore` contract:**

```python
class RedisApprovalStore:
    def put_pending(self, decision: PendingDecision) -> None:
        # SET pending:{decision.pending_id} <json> EX APPROVAL_TTL_SECONDS
        ...

    def pop_pending(self, pending_id: str) -> PendingDecision | None:
        # GETDEL pending:{pending_id}
        # If absent or TTL expired: return None
        # If expires_at < now(UTC): delete key, return None, log pending_expired
        ...

    def get_pending(self, pending_id: str) -> PendingDecision | None:
        # GET without deleting — for inspection only
        ...
```

**Serialisation:** Always use `decision.model_dump(mode="json")` before storing in Redis.
Always use `PendingDecision.model_validate_json(raw)` when reading back. Never pickle.

**`DedupCache` contract:**

```python
class DedupCache:
    def check(self, message_id: str) -> str | None:
        # GET dedup:{message_id}
        # Returns cached response JSON string or None
        ...

    def set(self, message_id: str, response_json: str) -> None:
        # SET dedup:{message_id} response_json EX 86400
        ...
```

**Redis key namespacing (do not deviate):**

| Key | TTL | Purpose |
|-----|-----|---------|
| `pending:{pending_id}` | `APPROVAL_TTL_SECONDS` | Durable approval decision |
| `dedup:{message_id}` | 86400 s | Idempotent response cache |
| `ratelimit:{user_id}` | 60 s | Rate limit counter (PR-7) |

**`app/store.py` changes:** Remove `_pending` dict and all methods that operate on it.
Keep only the SQLite event log logic.

**`app/agent.py` changes:** Accept `approval_store: RedisApprovalStore` as a constructor
parameter. Remove all references to `store._pending`.

**`app/main.py` changes:**
- In `lifespan`: create `redis.from_url(settings.redis_url)`, `RedisApprovalStore(redis)`,
  `DedupCache(redis)`.
- Before `process_webhook()`: check `dedup.check(request.message_id)` — if hit, return cached
  response immediately and log `dedup_hit`.
- After successful `process_webhook()`: call `dedup.set(request.message_id, response_json)`.
- If `message_id` is absent: generate a UUID, do not cache.

**Startup behaviour:** If `REDIS_URL` is set and Redis is unreachable at startup, raise
`RuntimeError` with a clear message. Do not degrade gracefully for Redis — missing Redis breaks
idempotency guarantees.

**New config vars:**

```python
redis_url: str = "redis://redis:6379"
```

**docker-compose.yml:** Add a `redis:7-alpine` service with `redis-cli ping` healthcheck.
Agent service depends on Redis.

**Acceptance criteria:**
1. Same `message_id` twice → identical responses, no second LLM call.
2. Absent `message_id` → processes on every call (no cache).
3. `POST /approve` resolves a `pending_id` created before agent restart.
4. `pending:{pending_id}` Redis key has TTL = `APPROVAL_TTL_SECONDS` (verify with `TTL` command).
5. Instance A creates pending; instance B resolves it via `/approve`.

**Tests:** Use `fakeredis.FakeRedis` (add to `requirements-dev.txt`).
- `tests/test_redis_approval_store.py`
- `tests/test_dedup.py`
- Update `tests/test_approval_flow.py` to inject `RedisApprovalStore(fakeredis.FakeRedis())`

---

## 5. PR-7 — Webhook Signature + Rate Limiting [P1]

**Goal:** Add HMAC-SHA256 signature verification and per-`user_id` Redis sliding-window rate limit.

**Files to create:**

- `app/middleware/__init__.py`
- `app/middleware/signature.py` — `SignatureMiddleware`
- `app/middleware/rate_limit.py` — `RateLimitMiddleware`

**`SignatureMiddleware`:**

```python
class SignatureMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not settings.webhook_secret:
            return await call_next(request)   # dev mode: skip
        if request.url.path != "/webhook":
            return await call_next(request)
        body = await request.body()
        expected = "sha256=" + hmac.new(
            settings.webhook_secret.encode(),
            body,
            hashlib.sha256
        ).hexdigest()
        received = request.headers.get("X-Webhook-Signature", "")
        if not hmac.compare_digest(expected, received):   # MUST use compare_digest
            return JSONResponse({"detail": "Invalid signature"}, status_code=401)
        return await call_next(request)
```

**CRITICAL:** Use `hmac.compare_digest()` — never `==`. This prevents timing oracle attacks.

**`RateLimitMiddleware`:**
- Key: `ratelimit:{user_id}` (parse `user_id` from request body JSON before routing).
- Algorithm: INCR + EXPIRE sliding window.
- If Redis unavailable: log `WARNING`, allow request.
- HTTP 429 response: `{"detail": "Rate limit exceeded"}`.

**Middleware registration order in `app/main.py`:**
1. `SignatureMiddleware` (first — rejects before any processing)
2. `RateLimitMiddleware`
3. `RequestIDMiddleware` (existing)

**New config vars:**

```python
webhook_secret: str | None = None
rate_limit_rpm: int = 10
rate_limit_burst: int = 3
```

**Acceptance criteria:**
1. No `X-Webhook-Signature` header + `WEBHOOK_SECRET` set → HTTP 401.
2. Correct signature → normal response.
3. Tampered body + original signature → HTTP 401.
4. `WEBHOOK_SECRET` unset → signature check skipped.
5. 11 requests from same `user_id` within 60 s → 11th returns HTTP 429.
6. Two different `user_id` values have independent counters.

**Tests:** `tests/test_middleware.py` — use `fakeredis` for rate limit tests.

---

## 6. PR-5 — Linear API Integration [P1]

**Goal:** Replace `create_ticket()` stub with a real Linear GraphQL mutation.

**Files to create:**

- `app/integrations/__init__.py`
- `app/integrations/linear.py` — `LinearClient`

**`LinearClient.create_issue()` signature:**

```python
def create_issue(
    self,
    title: str,
    description: str,
    priority: int,   # 1=Urgent, 2=High, 3=Medium, 4=Low
    team_id: str,
) -> dict[str, Any]:
    # Returns {"ticket_id": "ENG-42", "url": "https://linear.app/...", "status": "created"}
```

**GraphQL mutation (use `httpx`, not a generated client):**

```graphql
mutation CreateIssue($title: String!, $description: String, $priority: Int, $teamId: String!) {
  issueCreate(input: {
    title: $title, description: $description,
    priority: $priority, teamId: $teamId
  }) {
    success
    issue { id identifier url }
  }
}
```

**Priority mapping:**

| Urgency | Linear priority int |
|---------|---------------------|
| `critical` | 1 |
| `high` | 2 |
| `medium` | 3 |
| `low` | 4 |

**Error handling:**
- HTTP 429 → log `WARNING`, raise `HTTPException(503)`.
- HTTP 4xx → log `ERROR`, raise `HTTPException(500)` with safe message (no API response body).
- Missing `LINEAR_API_KEY` at startup → log `WARNING`, use stub fallback (return `TKT-*`).

**Update `app/tools/ticketing.py`:** Call `LinearClient.create_issue()` when `LINEAR_API_KEY` is set.

**Acceptance criteria:**
1. Gameplay question → Linear issue created; `action_result.ticket.ticket_id` matches Linear identifier.
2. `action_result.ticket.url` is a valid Linear issue URL.
3. Missing `LINEAR_API_KEY` → stub fallback, no crash.
4. Linear 429 → HTTP 503 to caller.
5. Linear 4xx → HTTP 500 with safe message.

**Tests:** `tests/test_linear_integration.py` — mock `httpx.Client.post()`.

---

## 7. PR-6 — Telegram Bot + Approval Buttons [P1]

**Goal:** Replace `send_reply()` stub with real Telegram delivery. Send approval notifications
with ✅/❌ inline buttons when an action is pending.

**Files to create:**

- `app/integrations/telegram.py` — `TelegramClient`

**`TelegramClient` methods:**

```python
def send_message(self, chat_id: str, text: str) -> dict[str, Any]:
    # POST https://api.telegram.org/bot{TOKEN}/sendMessage
    # Returns {"delivery": "sent", "message_id": <int>}

def send_approval_request(
    self,
    chat_id: str,       # TELEGRAM_APPROVAL_CHAT_ID, not the user's chat
    pending_id: str,
    draft: str,
    category: str,
    urgency: str,
    reason: str,
) -> str:              # returns message_id
    # Sends a message with inline_keyboard:
    # [✅ Approve: approve:{pending_id}] [❌ Reject: reject:{pending_id}]
    # callback_data max 64 bytes: "approve:" (8) + 32 = 40 bytes — safe
```

**Integration in `app/agent.py`:**
- After `put_pending()`, call `telegram.send_approval_request(TELEGRAM_APPROVAL_CHAT_ID, ...)`.
- Fire-and-forget for Telegram errors — log `WARNING`, do not surface as HTTP error.

**Error handling:**
- Missing `TELEGRAM_BOT_TOKEN` → log `WARNING`, stub returns `{"delivery": "queued"}`.
- Telegram 429 → log `WARNING`, do not raise.
- Absent `metadata.chat_id` → guard with `metadata.get("chat_id")` before calling `send_message`.

**Acceptance criteria:**
1. Low-risk message → Telegram reply sent to `metadata.chat_id`.
2. Pending message → approval notification sent to `TELEGRAM_APPROVAL_CHAT_ID` with inline buttons.
3. Button `callback_data` is `approve:{pending_id}` / `reject:{pending_id}`.
4. Missing `TELEGRAM_BOT_TOKEN` → stub, no crash.
5. Telegram 429 → no HTTP error surface.
6. Absent `metadata.chat_id` → no exception.

**Tests:** `tests/test_telegram_integration.py` — mock `httpx.AsyncClient`.

---

## 8. PR-8 — Eval Dataset Expansion [P1]

**Goal:** Expand `eval/cases.jsonl` to 25 labelled cases and update `eval/runner.py` to track
guard blocks as a distinct metric.

**Case schema (one JSON object per line):**

```json
{
  "id": 1,
  "text": "...",
  "expected_category": "billing",
  "expected_urgency": "high",
  "expected_guard": null
}
```

Injection cases: `"expected_guard": "input_blocked"`, `"expected_category": null`.

**Required distribution:**

| Category | Min cases |
|----------|-----------|
| `billing` | 5 |
| `account_access` | 4 |
| `bug_report` | 5 |
| `cheater_report` | 3 |
| `gameplay_question` | 4 |
| `other` | 1 |
| Injection (`expected_guard: "input_blocked"`) | 2 |
| Legal-keyword | 1 |

**Updated `eval/runner.py` output:**

```json
{
  "total": 23,
  "correct": 20,
  "guard_blocks": 2,
  "accuracy": 0.87,
  "guard_block_rate": 1.0,
  "per_label_accuracy": { "billing": 1.0, "bug_report": 0.8 }
}
```

Guard-blocked cases are counted in `guard_blocks`, excluded from `total` and `accuracy` denominator.

**Acceptance criteria:**
1. Exactly 25 cases with the distribution above.
2. `accuracy >= 0.85` (excluding guard cases).
3. `guard_block_rate == 1.0` for all injection cases.
4. `eval/results/last_run.json` committed with passing results.

**Tests:** `tests/test_eval_runner.py` — mock `AgentService`; verify counting logic.

---

## 9. PR-9 — Google Sheets Audit Log [P2]

**Goal:** Asynchronously append an audit row to Google Sheets after each completed action.

**Files to create:**

- `app/integrations/sheets.py` — `SheetsClient`
- Add `AuditLogEntry` Pydantic model to `app/schemas.py`

**Audit log columns (A–M, exact order — see `docs/N8N.md §7`):**

`timestamp`, `request_id`, `message_id`, `user_id` (SHA-256 hash), `category`, `urgency`,
`confidence`, `action`, `status`, `approved_by`, `ticket_id`, `latency_ms`, `cost_usd`

**Integration in `app/agent.py`:**
- After `execute_action()` (auto path) and after `approve()` (approval path), call
  `SheetsClient.append_log()` in a background thread (`asyncio.get_event_loop().run_in_executor`).
- The background write must not block the HTTP response.

**`user_id` hashing in production:**

```python
import hashlib
hashed_user_id = hashlib.sha256(user_id.encode()).hexdigest() if user_id else None
```

**Error handling:**
- Missing `GOOGLE_SHEETS_CREDENTIALS_JSON` → log `WARNING`, disable Sheets logging silently.
- Sheets API 429 → retry with 60 s delay (max 2 attempts), then log and give up.
- Any Sheets failure must not propagate as an HTTP error.

**Acceptance criteria:**
1. Auto-executed action → row in spreadsheet within 10 s.
2. Approved action → row with `status=approved`, `approved_by=<reviewer>`.
3. `/webhook` response latency does not increase (write is async).
4. Missing credentials → no crash.
5. Sheets 429 → no HTTP error.

**Tests:** `tests/test_sheets_integration.py` — mock `google-api-python-client`.

---

## 10. PR-10 — Docker Compose Full Stack + Demo Script [P2]

**Goal:** `docker compose up --build` starts the full stack (agent + Redis + n8n). A demo script
runs 3 scenario verifications.

**`docker-compose.yml` services:**

| Service | Image | Port | Healthcheck |
|---------|-------|------|-------------|
| `agent` | `Dockerfile` (Python 3.12-slim) | `8000` | `GET /health` |
| `redis` | `redis:7-alpine` | `6379` | `redis-cli ping` |
| `n8n` | `n8nio/n8n:1.x` | `5678` | `GET /healthz` |

All services share bridge network `gdev`. n8n reaches agent at `http://agent:8000`.

**`scripts/demo.sh` scenarios:**
1. Gameplay question → assert `status == "executed"`.
2. Billing dispute → assert `status == "pending"` + non-empty `pending_id`.
3. Prompt injection → assert HTTP 400 + `"Input failed injection guard"`.

Each scenario prints `PASS` or `FAIL`.

**`Dockerfile`:**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Acceptance criteria:**
1. `docker compose up --build` succeeds on a clean machine.
2. `GET localhost:8000/health` → `{"status": "ok"}`.
3. All 3 demo scenarios print `PASS`.

---

## 11. Global Constraints

### Must not violate

- `hmac.compare_digest()` for signature comparison — never `==`.
- `model_dump(mode="json")` when serialising Pydantic models to Redis.
- `datetime.now(UTC)` — never naive datetimes.
- `REQUEST_ID` ContextVar in all log `extra` dicts.
- HTTP status code semantics: 404 for not-found, 401 for auth, 429 for rate-limit.
- No secrets in log output. No `user_id` in plaintext in Sheets (SHA-256 hash).
- `TOOL_REGISTRY` as the only dispatch path — no `if action.tool ==` branches.

### Must include in every log call

```python
logger.info(
    "action executed",
    extra={
        "event": "action_executed",
        "context": {
            "category": ...,
            "urgency": ...,
            "confidence": ...,
            "latency_ms": ...,
            "pending_id": None,
        }
    }
)
```

### Must add to `app/config.py` and `.env.example`

Every new configuration parameter. Required params → startup failure if absent.
Optional integration params → `WARNING` + graceful fallback.

### Must test without network

All tests run without real API calls. Use:
- `fakeredis.FakeRedis` for Redis
- `unittest.mock.patch` for `httpx` calls (Linear, Telegram, Sheets)
- `FakeLLMClient` (already in test files) for LLM calls

### Eval gate

`eval/runner.py` must produce `accuracy >= 0.85` after every PR. Run it before merging.

### Engineering review checklist

Apply `docs/REVIEW_NOTES.md §2` and `§3` before every commit.

---

## 12. Definition of Done

A PR is complete when **all** of the following are true:

- [ ] All acceptance criteria for the PR pass in CI.
- [ ] New code has unit tests; no existing test is deleted without justification.
- [ ] `eval/runner.py` accuracy ≥ 0.85 (run against live API or mocked, document result).
- [ ] No new hardcoded values — all configurable items added to `app/config.py` and `.env.example`.
- [ ] `git grep -rn "sk-ant\|lin_api_\|Bearer " app/` returns no results.
- [ ] `docs/ARCHITECTURE.md` component status table updated to `✅` for the merged feature.
- [ ] `docs/REVIEW_NOTES.md` checklists consulted and all applicable boxes checked.
- [ ] `REVIEW_NOTES.md` open findings (N-2, N-3, N-5) updated if the PR resolves them.

---

## 13. Key Pitfalls (memorise before coding)

From `docs/REVIEW_NOTES.md §5`:

1. **Silent 200 on not-found** — always raise `HTTPException`, never return status strings.
2. **`user_id` lost across async** — always store in `PendingDecision`; pass `pending.user_id` on approval.
3. **Naive datetimes** — `datetime.now(UTC)`, never `datetime.now()`.
4. **Tool dispatch bypasses registry** — when adding a new LLM tool, update both `TOOLS` in `llm_client.py` AND `TOOL_REGISTRY` in `tools/__init__.py`.
5. **Redis key collisions** — only use the three prefixes: `dedup:`, `pending:`, `ratelimit:`.
6. **Approval token reuse** — n8n must treat HTTP 404 from `/approve` as terminal (not retriable).
7. **Output guard empty allowlist** — document that `URL_ALLOWLIST=` must be set before enabling guard in production.
8. **`answerCallbackQuery` 30 s deadline** — Telegram requires this before calling `/approve` in n8n.
