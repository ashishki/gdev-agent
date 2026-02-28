# gdev-agent — Review Notes v2.0

_Maintainer reference: 2026-02-28. Apply these checklists before merging every PR.
Version bumped on structural review update._

---

## 1. Historical Findings — Resolution Status

### 1.1 Original Engineering Review

| ID | Severity | Finding | Status |
|----|----------|---------|--------|
| C-1 | Critical | No LLM integration — classifier was keyword matching | ✅ Resolved — `app/llm_client.py` implements Claude `tool_use` loop |
| C-2 | Critical | `/approve` returned HTTP 200 when `pending_id` not found | ✅ Resolved — raises `HTTPException(404)` |
| C-3 | Critical | `user_id` discarded when storing `PendingDecision` | ✅ Resolved — `PendingDecision.user_id` preserved; passed to `execute_action()` on approval |
| C-4 | Critical | Pending approvals unbounded in memory, lost on restart | ✅ Resolved — `RedisApprovalStore` with TTL eviction |
| C-5 | Critical | SQLite used without WAL mode under multithreaded server | ✅ Resolved — `PRAGMA journal_mode=WAL` executed after connect |
| M-1 | Medium | Legal-keyword check produced `risky=False` with null `risk_reason` | ✅ Resolved — consolidated into `propose_action()`; always sets `risk_reason` |
| M-2 | Medium | Injection guard pattern list too narrow (4 patterns) | ✅ Resolved — expanded to 15 pattern classes |
| M-3 | Medium | `configure_logging()` called at module import time | ✅ Resolved — moved into `lifespan` context manager |
| M-4 | Medium | No request correlation ID | ✅ Resolved — `RequestIDMiddleware` + `REQUEST_ID` ContextVar |
| M-5 | Medium | Log timestamp reflected serialisation time, not event time | ✅ Resolved — uses `record.created` |
| M-6 | Medium | Error-code regex matched unrelated patterns (`E-Wallet`) | ✅ Resolved — anchored to `ERR[-_]?\d{3,}` / `E[-_]\d{4,}` |
| N-1 | Nice-to-have | `ensure_ascii=True` in logs and store | ✅ Resolved — `ensure_ascii=False` in `logging.py` and `store.py` |
| N-2 | Nice-to-have | Exception info dropped from JSON log lines | ❌ Open — PR-11 assigned |
| N-3 | Nice-to-have | `execute_action()` dispatch hardcoded | ✅ Resolved — `TOOL_REGISTRY` dict dispatch |
| N-4 | Nice-to-have | `latency_ms` not measured or logged | ✅ Resolved — `time.monotonic()` in `process_webhook()` |
| N-5 | Nice-to-have | Eval dataset 6 cases vs. 25 target | ✅ Resolved — expanded to 25 cases |

### 1.2 Strategic Review Findings (2026-02-28 — Phase 1)

| ID | Severity | Finding | Status |
|----|----------|---------|--------|
| B-1 | Low | `pop_pending()` calls `redis.delete(key)` after `GETDEL` (dead code) | ✅ Resolved — removed no-op delete after `GETDEL` |
| B-2 | Medium | Duplicate `Settings` + Redis at module load (`app/main.py:75-82`) | ⚠️ Open — PR-15 or standalone cleanup |
| B-3 | Low | `rate_limit_burst` configured but not enforced | ✅ Resolved — burst window enforcement added |
| B-4 | Low | `asyncio.get_event_loop()` deprecated in Python 3.12 | ✅ Resolved — uses `asyncio.get_running_loop()` |
| G-1 | Medium | `exc_info` not captured in `JsonFormatter` | ✅ Resolved — traceback emitted as `exc_info` |
| G-2 | Medium | `RATE_LIMIT_BURST` not enforced | ✅ Resolved — enforced via `ratelimit_burst:{user_id}` |
| G-3 | Low | `cost_usd` always `0.0` | ✅ Resolved — token-based cost estimation wired |
| G-4 | Low | LLM `draft_reply` tool output unused | ✅ Resolved — `triage.draft_text` is now used |
| G-7 | Medium | Approval notification is fire-and-forget with no fallback | ⚠️ Open — no PR assigned |
| G-8 | Low | No CI check for TOOLS / TOOL_REGISTRY sync | ✅ Resolved — registry/schema sync test added |
| M-7 | Low | Missing `Retry-After` header on HTTP 429 | ✅ Resolved — middleware returns `Retry-After: 60` |
| M-8 | Medium | No startup warning when `WEBHOOK_SECRET` is unset | ✅ Resolved — startup `security_degraded` warning added |

---

## 2. Engineering Review Checklist

Apply to **every PR** before merge.

### 2.1 Correctness

- [ ] Does the code behave as described by the acceptance criteria?
- [ ] Are all edge cases (empty input, `None` fields, expired tokens) handled explicitly?
- [ ] Are HTTP status codes semantically correct? (`404` for not-found, `401` for auth, `429` for rate-limit — never `200` for errors)
- [ ] Are there silent failures? (`try/except Exception: pass` is a red flag — log and re-raise or handle explicitly)
- [ ] Is `user_id` preserved from `WebhookRequest` through `PendingDecision` to `execute_action()`?
- [ ] Is `message_id` provided by the caller? If absent, is the response explicitly not cached?

### 2.2 Data Integrity

- [ ] Does `PendingDecision` carry an `expires_at` field set at creation time?
- [ ] Does `pop_pending()` evict entries past `expires_at` before returning them?
- [ ] Are all `datetime` values timezone-aware UTC (`datetime.now(UTC)`)? No naive datetimes.
- [ ] Is `model_dump(mode="json")` used when serialising Pydantic models to Redis or SQLite?
- [ ] Is `PendingDecision.model_validate_json(raw)` used when reading back from Redis? Never pickle.

### 2.3 Logging

- [ ] Does every `logger.info()` call include `extra={"event": "...", "context": {...}}`?
- [ ] Is `latency_ms` included in every `action_executed` and `pending_action` log entry?
- [ ] Does no log line interpolate a secret value (`ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, raw `user_id`)?
- [ ] Is `user_id` hashed before appearing in Sheets or any audit log?
- [ ] Is the `timestamp` field derived from `record.created`, not `datetime.now()`?
- [ ] If the PR adds `logger.exception()` calls: does the JSON log include `exc_info` after PR-11?

### 2.4 Configuration

- [ ] Are all new configuration parameters added to `app/config.py` and `.env.example`?
- [ ] Do required parameters cause startup failure with a clear error message if absent?
- [ ] Do optional integration parameters log a `WARNING` and fall back gracefully if absent?
- [ ] Are default values safe for production (e.g., `OUTPUT_GUARD_ENABLED=true`, `WEBHOOK_SECRET` warns if absent)?

### 2.5 Tests

- [ ] Are new acceptance criteria covered by tests that run without network access (mocked LLM, `fakeredis`, `httpx` mocks)?
- [ ] Does `eval/runner.py` produce `accuracy ≥ 0.85` after this change?
- [ ] Does the test file name match the feature (`test_tool_registry.py`, not `test_misc.py`)?
- [ ] Are there no tests that mutate global state without cleanup (e.g., `TOOL_REGISTRY` modified in a test)?
- [ ] Does `FakeLLMClient` return non-zero `input_tokens` and `output_tokens` after PR-13?

### 2.6 Extensibility

- [ ] Can a new tool be added without modifying `agent.py`? (Requires `TOOL_REGISTRY` in place — it is.)
- [ ] Can a new support category be added with changes to ≤ 4 files?
- [ ] Does adding a new input channel require only an n8n node change, with no application code modification?
- [ ] If a new LLM tool was added to `TOOLS`, is it also in `TOOL_REGISTRY` (or explicitly exempt, like `flag_for_human`)?

---

## 3. Security / Safety Checklist

Apply to PRs that touch guards, auth, secrets, or external integrations.

### 3.1 Input Guard

- [ ] Does `_guard_input()` run **before** any LLM API call?
- [ ] Is the pattern list checked case-insensitively (text lowercased before match)?
- [ ] Are new injection patterns tested against the eval injection cases?
- [ ] Does a guard block produce HTTP 400 with `"Input failed injection guard"` and an `event: "guard_blocked"` log?
- [ ] Were new patterns checked for false positives against realistic player messages?

### 3.2 Output Guard

- [ ] Does `OutputGuard.scan()` run **after** `llm_client.run_agent()` and **before** the response is returned?
- [ ] Does a secret match produce HTTP 500 (internal error, not HTTP 400)?
- [ ] Does the HTTP 500 `detail` **not** include the matched secret string?
- [ ] Is `OUTPUT_GUARD_ENABLED=true` the default in `.env.example`?
- [ ] Is `URL_ALLOWLIST` documented as empty by default (strips all URLs until configured)?
- [ ] Is the confidence floor (`< 0.5`) tested with a case that has `confidence=0.3`?
- [ ] Does `OutputGuard.scan()` avoid mutating shared state? (Note: currently mutates `action` argument — acceptable until refactored.)

### 3.3 Secrets

- [ ] Does `git grep -rn "sk-ant\|lin_api_\|Bearer " app/` return no results?
- [ ] Does `.gitignore` include `.env`, `*.key`, `secrets/`?
- [ ] Are no secrets interpolated in f-strings that appear in log lines?
- [ ] Is `user_id` hashed (`sha256(user_id).hexdigest()`) before appearing in Sheets or external audit logs?
- [ ] Does the service-account JSON credentials path never appear in log output?

### 3.4 Webhook Signature

- [ ] Is `hmac.compare_digest()` used (not `==`) for signature comparison?
- [ ] Is the raw request body read **before** JSON parsing (Starlette middleware, not FastAPI dependency)?
- [ ] Does an absent or malformed `X-Webhook-Signature` header return HTTP 401 (when secret is set)?
- [ ] Does a correct signature on a tampered body return HTTP 401?
- [ ] Does the agent log a `WARNING` with `event: "security_degraded"` at startup when `WEBHOOK_SECRET` is unset (after PR-16)?

### 3.5 Approval Flow

- [ ] Is `pending_id` a 32-char random hex (`uuid4().hex`)? No sequential or predictable IDs.
- [ ] Does `pop_pending()` remove the entry atomically (GETDEL — no TOCTOU race)?
- [ ] Is `/approve` inaccessible from the public internet in production (VPC restriction or `APPROVE_SECRET` header)?
- [ ] Is the `reviewer` field logged but never used for authorisation decisions?
- [ ] Is a second `POST /approve` call with the same `pending_id` returning HTTP 404 (not HTTP 200)?

### 3.6 Rate Limiting and DoS

- [ ] Does the rate limiter degrade gracefully if Redis is unavailable (allow request, log warning)?
- [ ] Does the rate limit key use the `ratelimit:` prefix (not colliding with `dedup:` or `pending:`)?
- [ ] Is there a guard against zero-length or whitespace-only `text` fields (`min_length=1` in `WebhookRequest`)?
- [ ] After PR-12: does `ratelimit_burst:` use a separate key from `ratelimit:`?

---

## 4. n8n Workflow Review Checklist

Apply when importing, modifying, or deploying n8n workflows.

### 4.1 Workflow Import

- [ ] Does the workflow JSON import without errors into the target n8n version (1.x)?
- [ ] Are all required credentials listed in `n8n/README.md`?
- [ ] Is the n8n version pinned in `docker-compose.yml`?

### 4.2 Triage Workflow

- [ ] Does the Telegram Trigger filter for `message` type only (not `edited_message`, `callback_query`)?
- [ ] Does the Normalize Function node produce a valid `WebhookRequest` body?
- [ ] Does the HTTP Request node include `X-Webhook-Signature` and `X-Request-ID` headers?
- [ ] Does the `status == "pending"` branch send approval buttons to `TELEGRAM_APPROVAL_CHAT_ID` (not the user's chat)?
- [ ] Is `callback_data` format `approve:{pending_id}` / `reject:{pending_id}` (≤ 64 bytes total)?
- [ ] Is the retry chain set to max 3 attempts with delays of 30 s and 90 s?
- [ ] Is HTTP 400 configured as non-retriable (terminal — guard block)?
- [ ] Is HTTP 500 from the output guard configured as non-retriable (terminal — same input will always fail)?
- [ ] Does the Error Workflow notify the ops Telegram channel (not the user's chat)?

### 4.3 Approval Callback Workflow

- [ ] Does the Trigger respond to `callback_query` events?
- [ ] Is `answerCallbackQuery` called **before** `POST /approve`? (30 s Telegram deadline)
- [ ] Does the workflow handle both `approve:` and `reject:` prefixes?
- [ ] Does it extract `reviewer` from `callback_query.from.id`?
- [ ] Does a 404 from `POST /approve` (expired/consumed token) produce a user-facing "expired" message and **not** retry?

### 4.4 Data Handling

- [ ] Does the Normalize node sanitise `text` (trim whitespace) before sending to the agent?
- [ ] Is `message_id` cast to string (Telegram's `message_id` is an integer)?
- [ ] Is `metadata.chat_id` cast to string?

---

## 5. Common Pitfalls

### 5.1 Silent 200 on Not-Found

**What goes wrong:** A function returns a status string like `"not_found"` instead of raising an exception; the endpoint returns HTTP 200. Callers assume success.

**How to avoid:** Never use status strings to represent HTTP-level errors. Raise `HTTPException` with the correct status code. Remove `"not_found"` from `Literal` types in response schemas.

---

### 5.2 User Identity Lost Across Async Boundaries

**What goes wrong:** `user_id` is present in the incoming request but not stored in `PendingDecision`. When approval fires hours later, the reply has no destination.

**How to avoid:** Always store `user_id` in `PendingDecision`. Always pass `pending.user_id` (not `None`) to `execute_action()` in the approval path. Test with: `action_result["reply"]["user_id"] == original_user_id`.

---

### 5.3 Naive Datetimes in TTL Comparisons

**What goes wrong:** `datetime.now()` (no timezone) compared against `expires_at` (UTC-aware) → `TypeError: can't compare offset-naive and offset-aware datetimes`.

**How to avoid:** Always `datetime.now(UTC)`. Import `UTC` from `datetime` (Python 3.11+). Never create naive datetimes. The existing codebase uses `from datetime import UTC` — maintain this.

---

### 5.4 Tool Dispatch Bypasses Registry

**What goes wrong:** A new tool is added to `TOOLS` in `llm_client.py` but not to `TOOL_REGISTRY`. The model returns a `tool_use` block with the new name; `execute_action()` raises `ValueError`.

**How to avoid:** When adding a new LLM-callable tool, always update both `TOOLS` in `llm_client.py` **and** `TOOL_REGISTRY` in `tools/__init__.py`. Exception: `flag_for_human` is LLM-callable but is explicitly excluded from `TOOL_REGISTRY` because it always routes to the pending path (see `ARCHITECTURE.md §5.1`).

---

### 5.5 Redis Key Collisions

**What goes wrong:** Two features use the same Redis key prefix. One evicts the other's keys.

**How to avoid:** Use the namespacing contract from `ARCHITECTURE.md §6.2`:
- `dedup:{message_id}` — idempotency cache
- `pending:{pending_id}` — approval decisions
- `ratelimit:{user_id}` — rate limit counters (minute window)
- `ratelimit_burst:{user_id}` — rate limit counters (burst window, after PR-12)

Never reuse these prefixes. Add new prefixes to `ARCHITECTURE.md §6.2` before implementing.

---

### 5.6 Approval Token Reuse

**What goes wrong:** `pop_pending()` removes the entry atomically, but a retry in n8n re-sends `POST /approve` with the same `pending_id`. The second call returns HTTP 404.

**How to avoid:** n8n must treat HTTP 404 from `/approve` as terminal — not retriable. Configure the n8n HTTP Request node: On 404 → abort and notify user "approval expired".

---

### 5.7 Injection Pattern False Positives

**What goes wrong:** A legitimate player message contains `"act as"` (e.g., "The game forces you to act as a villain"). The message is blocked with HTTP 400.

**How to avoid:** Before adding new patterns, test against the full eval dataset. Prefer longer, more specific phrases. Track false positive rate as a metric.

---

### 5.8 LLM Response with No Tool Calls

**What goes wrong:** Claude returns `stop_reason == "end_turn"` without calling `classify_request`. The fallback fires: `ClassificationResult(category="other", urgency="low", confidence=0.0)`.

**How to avoid:** The fallback is intentional and safe — confidence 0.0 triggers the approval gate. A `WARNING` log is emitted when the fallback fires. If this happens frequently, inspect the system prompt in `llm_client.py` and ensure it mandates calling `classify_request`.

---

### 5.9 Output Guard Strips All Drafts (Empty Allowlist)

**What goes wrong:** `URL_ALLOWLIST` is empty (default). The LLM includes a KB link in the draft. The output guard strips it. Support replies never contain useful links.

**How to avoid:** Set `URL_ALLOWLIST` to your KB domain(s) before deploying with output guard enabled. Monitor `output_guard_redacted` events in the first 24 h after rollout.

---

### 5.10 n8n Sends Approval Buttons to Wrong Chat

**What goes wrong:** Approval notification (with ✅/❌ buttons) sent to `metadata.chat_id` (the user's chat) instead of `TELEGRAM_APPROVAL_CHAT_ID` (internal support group).

**How to avoid:** The Triage Workflow must branch:
- `status == "executed"`: reply to `metadata.chat_id`.
- `status == "pending"`: send approval notification to `TELEGRAM_APPROVAL_CHAT_ID`.

These are two different HTTP Request nodes with different `chat_id` values.

---

### 5.11 Dedup Caches Pending Response — Stale `pending_id`

**What goes wrong:** A `status: "pending"` response is cached for 24 h. A duplicate `message_id` request returns the cached response with the same `pending_id`. If the original token was approved or rejected, the caller's `/approve` call returns HTTP 404.

**How to avoid:** n8n must treat HTTP 404 from `/approve` as terminal. Document this explicitly: "a cached `pending_id` may already be consumed". This is correct by-design — not an error. The approver receives "approval expired or already processed".

---

### 5.12 Approval Notification Failure Is Silent

**What goes wrong:** If `_notify_approval_channel()` fails (Telegram down), the webhook returns `status: "pending"` successfully. The pending entry is in Redis. But the operator never receives the approval notification. The pending entry silently expires after `APPROVAL_TTL_SECONDS`.

**How to avoid:** Monitor `approval_notify_failed` log events. Implement a recovery mechanism (gap G-7): a scheduled n8n workflow that polls for unnotified pending entries, or a webhook to the agent that re-triggers notification. Until G-7 is resolved, set up alerting on `approval_notify_failed` log events.

---

### 5.13 `OutputGuard.scan()` Mutates Its Input

**What goes wrong:** `OutputGuard.scan()` is named like a pure function but mutates the `ProposedAction` argument when `confidence < 0.5`. If the same `ProposedAction` object is inspected before and after `scan()`, it has different values. Future refactors that cache or log the action before scanning will observe incorrect data.

**How to avoid:** Treat `action` as immutable after `scan()` returns. Do not call `scan()` more than once per request. When refactoring, consider returning a new `ProposedAction` from `scan()` instead of mutating.
