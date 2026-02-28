# gdev-agent — Review Notes

_Maintainer reference: 2026-02-28. Use these checklists before merging every PR._

---

## 1. Historical Findings — Resolution Status

The table below tracks findings from the initial engineering review. All findings were against the
original implementation; items marked ✅ are resolved in the current codebase.

| ID | Severity | Finding | Status |
|----|----------|---------|--------|
| C-1 | Critical | No LLM integration — classifier was keyword matching | ✅ Resolved — `app/llm_client.py` implements Claude `tool_use` loop |
| C-2 | Critical | `/approve` returned HTTP 200 when `pending_id` not found | ✅ Resolved — raises `HTTPException(404)` |
| C-3 | Critical | `user_id` discarded when storing `PendingDecision` | ✅ Resolved — `PendingDecision` carries `user_id`; passed to `execute_action()` on approval |
| C-4 | Critical | Pending approvals unbounded in memory, lost on restart | ✅ Resolved (MVP) — `expires_at` field, TTL eviction in `pop_pending()`; Redis target is PR-1 |
| C-5 | Critical | SQLite used without WAL mode under multithreaded server | ✅ Resolved — `PRAGMA journal_mode=WAL` executed after connect |
| M-1 | Medium | Legal-keyword check in `needs_approval()` produced `risky=False` with null `risk_reason` | ✅ Resolved — consolidated into `propose_action()`; `needs_approval()` returns `action.risky` |
| M-2 | Medium | Injection guard pattern list too narrow (4 patterns) | ✅ Resolved — expanded to 15 pattern classes |
| M-3 | Medium | `configure_logging()` called at module import time | ✅ Resolved — moved into `lifespan` context manager |
| M-4 | Medium | No request correlation ID | ✅ Resolved — `request_id_middleware` + `REQUEST_ID` ContextVar |
| M-5 | Medium | Log timestamp reflected serialisation time, not event time | ✅ Resolved — uses `record.created` |
| M-6 | Medium | Error-code regex matched unrelated patterns (`E-Wallet`) | ✅ Resolved — anchored to `ERR-\d{3,}` / `E-\d{4,}` |
| N-1 | Nice-to-have | `ensure_ascii=True` in logs and store | ✅ Resolved — `ensure_ascii=False` in `logging.py` and `store.py` |
| N-2 | Nice-to-have | Exception info dropped from JSON log lines | ⚠️ Open — `JsonFormatter` does not include `exc_info` |
| N-3 | Nice-to-have | `execute_action()` dispatch hardcoded, ignores `action.tool` | ✅ Resolved — dispatch now uses `TOOL_REGISTRY` |
| N-4 | Nice-to-have | `latency_ms` not measured or logged | ✅ Resolved — `time.monotonic()` in `process_webhook()` |
| N-5 | Nice-to-have | Eval dataset 6 cases vs. 25 target | ✅ Resolved — dataset expanded to 25 cases with guard labels |

---

## 2. Engineering Review Checklist

Apply to **every PR** before merge.

### 2.1 Correctness

- [ ] Does the code behave as described by the acceptance criteria?
- [ ] Are all edge cases (empty input, `None` fields, expired tokens) handled explicitly?
- [ ] Are HTTP status codes semantically correct? (`404` for not-found, not `200`; `401` for auth failures, not `403`)
- [ ] Are no silent failures present? (`try/except Exception: pass` is a red flag — log and re-raise or handle explicitly)
- [ ] Is `user_id` preserved from `WebhookRequest` through `PendingDecision` to `execute_action()`?

### 2.2 Data Integrity

- [ ] Does `PendingDecision` carry an `expires_at` field? Is it set at creation time?
- [ ] Does `pop_pending()` evict entries past `expires_at` before returning them?
- [ ] Are all `datetime` values timezone-aware (UTC)? No naive datetimes.
- [ ] Is `model_dump(mode="json")` used when serialising Pydantic models to Redis or SQLite? (`datetime` fields must serialize as strings, not Python objects)

### 2.3 Logging

- [ ] Does every `logger.info()` call include an `extra={"event": "...", "context": {...}}` dict?
- [ ] Is `latency_ms` included in every `action_executed` and `pending_action` log entry?
- [ ] Does no log line interpolate a secret value? (`ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, raw `user_id`)
- [ ] Does `logger.exception()` produce a JSON line with a non-null `exc_info` field? (Currently open — N-2)
- [ ] Is the `timestamp` field derived from `record.created`, not `datetime.now()`?

### 2.4 Configuration

- [ ] Are all new configuration parameters added to `app/config.py` and `.env.example`?
- [ ] Do required parameters cause startup failure with a clear error message if absent?
- [ ] Do optional integration parameters (Linear, Telegram) log a `WARNING` and fall back gracefully if absent?
- [ ] Are default values safe for production (e.g., `OUTPUT_GUARD_ENABLED=true`, not `false`)?

### 2.5 Tests

- [ ] Are new acceptance criteria covered by tests that run without network access (mocked LLM, `fakeredis`, `httpx` mocks)?
- [ ] Does `eval/runner.py` produce `accuracy ≥ 0.85` after this change?
- [ ] Does the test file name match the feature being tested (`test_tool_registry.py`, not `test_misc.py`)?
- [ ] Are there no tests that mutate global state without cleanup (e.g., `TOOL_REGISTRY` modification in a test)?

### 2.6 Extensibility

- [ ] Can a new tool be added without modifying `agent.py`? (Requires PR-3 to be merged first)
- [ ] Can a new support category be added with changes to ≤ 4 files?
- [ ] Does adding a new input channel require only an n8n node change, with no application code modification?

---

## 3. Security / Safety Checklist

Apply to PRs that touch guards, auth, secrets, or external integrations.

### 3.1 Input Guard

- [ ] Does `_guard_input()` run **before** any LLM API call is made?
- [ ] Is the pattern list checked case-insensitively (text lowercased before match)?
- [ ] Are new injection patterns tested against the eval injection cases?
- [ ] Does a guard block produce HTTP 400 with `"Input failed injection guard"` and an `event: "guard_blocked"` log entry?

### 3.2 Output Guard (PR-2+)

- [ ] Does `_guard_output()` run **after** `llm_client.run_agent()` and **before** the response is returned?
- [ ] Does a secret match produce HTTP 500 (not HTTP 400 — this is an internal failure, not a client error)?
- [ ] Does the HTTP 500 `detail` message **not** include the matched secret string?
- [ ] Is `OUTPUT_GUARD_ENABLED=true` the default in `.env.example`?
- [ ] Is `URL_ALLOWLIST` documented as empty by default (blocks all URLs until configured)?
- [ ] Is the confidence floor (< 0.5) tested with a case that has `confidence=0.3`?

### 3.3 Secrets

- [ ] Does `git grep -rn "sk-ant\|lin_api_\|Bearer " app/` return no results?
- [ ] Does `.gitignore` include `.env`, `*.key`, `secrets/`?
- [ ] Are no secrets interpolated in f-strings that appear in log lines?
- [ ] Is `user_id` hashed (`sha256(user_id).hexdigest()`) before appearing in Sheets logs (PR-9+)?
- [ ] Does the service-account JSON credentials path never appear in log output?

### 3.4 Webhook Signature (PR-7+)

- [ ] Is `hmac.compare_digest()` used (not `==`) to prevent timing oracle attacks?
- [ ] Is the raw request body read **before** JSON parsing (Starlette middleware, not FastAPI dependency)?
- [ ] Is `WEBHOOK_SECRET` validated as non-empty at startup when signature checking is enabled?
- [ ] Does an absent or malformed `X-Webhook-Signature` header return HTTP 401?
- [ ] Does a correct signature on a tampered body return HTTP 401?

### 3.5 Approval Flow

- [ ] Is `pending_id` a 32-char random hex (`uuid4().hex`)? No sequential IDs or predictable values.
- [ ] Does `pop_pending()` remove the entry atomically (no TOCTOU race between read and delete)?
- [ ] Is `/approve` inaccessible from the public internet in production? (VPC restriction or shared secret header)
- [ ] Is the `reviewer` field logged but never used for authorisation decisions?

### 3.6 Rate Limiting and DoS

- [ ] Does the rate limiter degrade gracefully if Redis is unavailable (allow request, log warning)?
- [ ] Does the rate limit key use the `ratelimit:` prefix to avoid collision with `dedup:` and `pending:` keys?
- [ ] Is there a guard against zero-length or whitespace-only `text` fields? (`text: str = Field(..., min_length=1)` in `WebhookRequest`)

---

## 4. n8n Workflow Review Checklist

Apply when importing, modifying, or deploying n8n workflows (`n8n/*.json`).

### 4.1 Workflow Import

- [ ] Does the workflow JSON import without errors into the target n8n version?
- [ ] Are all required credentials (agent URL, Telegram token, webhook secret) listed in `n8n/README.md`?
- [ ] Is the n8n version pinned in `docker-compose.yml`?

### 4.2 Triage Workflow

- [ ] Does the Telegram Trigger node filter for `message` type only (not `edited_message`, `channel_post`)?
- [ ] Does the Normalize Function node produce a valid `WebhookRequest` body with all required fields?
- [ ] Does the HTTP Request node include `X-Webhook-Signature` and `X-Request-ID` headers?
- [ ] Does the `status == "pending"` branch send approval buttons to `TELEGRAM_APPROVAL_CHAT_ID`, not back to the user?
- [ ] Is the `callback_data` format `approve:{pending_id}` or `reject:{pending_id}` (fits within 64 bytes)?
- [ ] Is the Google Sheets append node configured to write all 13 audit columns in the correct order?
- [ ] Is the retry chain set to max 3 attempts with delays of 30 s and 90 s?
- [ ] Does the Error Workflow notify the ops Telegram channel, not the user's chat?

### 4.3 Approval Callback Workflow

- [ ] Does the Webhook Trigger node respond to Telegram `callback_query` events?
- [ ] Is `answerCallbackQuery` called **before** calling `POST /approve`? (Telegram requires a response within 30 s)
- [ ] Does the workflow handle both `approve:` and `reject:` prefixes from `callback_data`?
- [ ] Does it extract `reviewer` from the Telegram user object (`callback_query.from.id` or `username`)?
- [ ] Does a 404 response from `POST /approve` (expired token) produce a user-facing error message ("Approval expired")?

### 4.4 Wait / Timeout Handling

- [ ] Is the Wait node timeout (if used) set to ≤ `APPROVAL_TTL_SECONDS`? Calling `/approve` after the token expires produces HTTP 404.
- [ ] Does a Wait timeout trigger the ops alert path, not retry?

### 4.5 Data Handling

- [ ] Does the Normalize node sanitise `text` (trim leading/trailing whitespace) before sending to the agent?
- [ ] Is `message_id` populated from Telegram's `message.message_id` field (cast to string)?
- [ ] Is `metadata.chat_id` populated from `message.chat.id` (cast to string)?

---

## 5. Common Pitfalls

These issues have recurred in this codebase or are common in similar systems. Check for them proactively.

### 5.1 Silent 200 on Not-Found

**What goes wrong:** A function returns a status string like `"not_found"` instead of raising an
exception; the endpoint passes a 200 through. Callers (n8n, scripts) assume success.

**How to avoid:** Never use status strings to represent HTTP-level errors. Raise `HTTPException` with
the appropriate status code. Remove `"not_found"` from `Literal` types in response schemas.

**Reference:** Previously C-2 in this codebase. Now fixed — but watch for new endpoints.

---

### 5.2 User Identity Lost Across Async Boundaries

**What goes wrong:** `user_id` is present in the incoming request but not stored in the
`PendingDecision`. When the approval fires hours later, the reply has no destination.

**How to avoid:** Always store `user_id` in `PendingDecision`. Always pass `pending.user_id`
(not `None`) to `execute_action()` in the approval path. Test with an assertion:
`action_result["reply"]["user_id"] == original_user_id`.

---

### 5.3 Naive Datetimes in TTL Comparisons

**What goes wrong:** `datetime.now()` (no timezone) is compared against `expires_at` (UTC-aware).
Python raises `TypeError: can't compare offset-naive and offset-aware datetimes`.

**How to avoid:** Always use `datetime.now(UTC)`. Import `UTC` from `datetime` (Python 3.11+).
Never create naive datetimes. The existing codebase uses `from datetime import UTC` — maintain this.

---

### 5.4 Tool Dispatch Bypasses Registry

**What goes wrong:** A new tool is added to `TOOLS` in `llm_client.py` (so the model can call it)
but not added to `TOOL_REGISTRY`. The model returns a `tool_use` block with the new tool name;
`execute_action()` looks it up in the registry, finds nothing, and raises.

**How to avoid:** When adding a new LLM-callable tool, always update **both** `TOOLS` in
`llm_client.py` (so Claude knows about it) **and** `TOOL_REGISTRY` in `tools/__init__.py`
(so the dispatcher can execute it).

---

### 5.5 Redis Key Collisions

**What goes wrong:** Two features use the same Redis key prefix (`pending:` for approvals and
`pending:` for something else). One feature evicts the other's keys.

**How to avoid:** Use the namespacing contract from `ARCHITECTURE.md §6.2`:
- `dedup:{message_id}` — idempotency cache
- `pending:{pending_id}` — approval decisions
- `ratelimit:{user_id}` — rate limit counters

Never reuse these prefixes for other purposes. Add new prefixes to `ARCHITECTURE.md` before implementing.

---

### 5.6 Approval Token Reuse

**What goes wrong:** `pop_pending()` removes the entry from the store, but a retry in n8n re-sends
`POST /approve` with the same `pending_id`. The second call returns HTTP 404 — correct, but n8n's
retry logic interprets this as a transient failure and retries again.

**How to avoid:** n8n must treat HTTP 404 from `/approve` as a terminal condition (token expired or
already consumed), not a retriable error. Configure the n8n HTTP Request node to not retry on 404.
Document this in `docs/N8N.md` under "Failure Modes".

---

### 5.7 Injection Pattern False Positives

**What goes wrong:** A legitimate player message contains a phrase that matches an injection pattern
(e.g., "The NPC tells me to **act as** a knight"). The message is blocked with HTTP 400.

**How to avoid:** Patterns are checked as substrings, not word-bounded, so short patterns carry risk.
Before adding new patterns, test them against the full eval dataset (`eval/cases.jsonl`). Prefer
longer, more specific phrases. Track false positive rate as a metric in eval runs.

---

### 5.8 LLM Response with No Tool Calls

**What goes wrong:** Claude returns `stop_reason == "end_turn"` without ever calling
`classify_request`. The loop exits without setting `classification`, triggering the fallback:
`ClassificationResult(category="other", urgency="low", confidence=0.0)`.

**How to avoid:** The fallback is intentional and safe — it triggers the approval gate via
`confidence < AUTO_APPROVE_THRESHOLD`. Do not remove the fallback. If this happens frequently,
inspect the system prompt in `llm_client.py` and ensure it mandates calling `classify_request`.
Log a `WARNING` when the fallback fires.

---

### 5.9 Output Guard Blocks All Drafts (Empty Allowlist)

**What goes wrong:** `URL_ALLOWLIST` is empty (default). The LLM includes a knowledge-base link
in the draft reply. The output guard strips or rejects it. Support replies never contain links.

**How to avoid:** Set `URL_ALLOWLIST` to your KB domain(s) before deploying with output guard
enabled. Monitor `output_guard_redacted` log events in the first 24 h after rollout.

---

### 5.10 n8n Sends Approval Buttons to Wrong Chat

**What goes wrong:** The approval notification (with ✅/❌ buttons) is sent to `metadata.chat_id`
(the user's chat) instead of `TELEGRAM_APPROVAL_CHAT_ID` (the internal support group).

**How to avoid:** The Triage Workflow must branch:
- `status == "executed"`: reply to `metadata.chat_id`.
- `status == "pending"`: send approval notification to `TELEGRAM_APPROVAL_CHAT_ID`.

These are two different HTTP Request nodes with different `chat_id` values. Confirm this in the
n8n workflow review checklist before activating.
