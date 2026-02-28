# gdev-agent — Implementation Plan

_Each PR is scoped to be reviewable in one session and deployable independently.
Work within each priority tier in listed order; tiers may overlap if development is parallel._

---

## Priority Key

| Level | Meaning |
|-------|---------|
| **P0** | Required for correct n8n orchestration and multi-instance deployment. Merge before exposing to real traffic. |
| **P1** | Required for production readiness. Ship before public launch. |
| **P2** | Operational polish. Ship iteratively after launch. |

---

## Recommended Merge Order

```
PR-3 → PR-2 → PR-1 → PR-7 → PR-5 → PR-6 → PR-4 → PR-8 → PR-9 → PR-10
```

PR-3 is a pure refactor with zero risk. PR-2 and PR-1 are safety-critical and gate everything else.
PR-4 (n8n workflow) requires PR-5 and PR-6 to work end-to-end, so it ships last in the P0 tier.

---

## PR-1 · Redis Approval Store + Idempotency Dedup [P0]

**Scope:** Replace the in-memory pending dict with a Redis-backed store so pending approvals survive
restarts and work across multiple agent instances; add per-`message_id` idempotency caching so
duplicate webhook calls return the same response without reprocessing.

**Files touched:**

- `app/approval_store.py` *(new)* — `RedisApprovalStore`: `put_pending()`, `pop_pending()`, `get_pending()`
- `app/dedup.py` *(new)* — `DedupCache`: `check(message_id) -> str | None`, `set(message_id, response_json, ttl)`
- `app/store.py` — remove `_pending` dict and all approval methods; keep SQLite event log only
- `app/agent.py` — accept `approval_store: RedisApprovalStore` as constructor parameter; remove in-memory dict usage
- `app/main.py` — inject `RedisApprovalStore` from lifespan; add dedup check before `process_webhook()`
- `app/config.py` — add `redis_url: str = "redis://redis:6379"`
- `docker-compose.yml` *(new or update)* — add `redis:7-alpine` service with healthcheck
- `.env.example` — document `REDIS_URL`

**Redis key contracts:**

| Key | Value | TTL |
|-----|-------|-----|
| `pending:{pending_id}` | JSON-serialised `PendingDecision` | `APPROVAL_TTL_SECONDS` |
| `dedup:{message_id}` | JSON-serialised `WebhookResponse` | 86 400 s |

**Acceptance criteria:**

1. `POST /webhook` with the same `message_id` twice returns identical response bodies; no LLM call is made on the second request.
2. `POST /webhook` with `message_id` absent processes normally on every call (no dedup).
3. `POST /approve` with a valid `pending_id` executes the action and returns HTTP 200.
4. After killing and restarting the agent process, a `pending_id` created before the restart is still resolvable via `POST /approve`.
5. With two agent instances running, `POST /approve` sent to instance B resolves a `pending_id` created by instance A.
6. A Redis key `pending:{pending_id}` has a TTL set equal to `APPROVAL_TTL_SECONDS` (verify with `TTL` command).

**Tests required:**

- `tests/test_redis_approval_store.py`: `put_pending()` / `pop_pending()` round-trip; expiry eviction; unknown key returns `None`. Use `fakeredis.FakeRedis` — add to `requirements-dev.txt`.
- `tests/test_dedup.py`: first call processes; second call returns cached body; absent `message_id` skips cache.
- Update `tests/test_approval_flow.py` to inject `RedisApprovalStore` using `fakeredis`.

**Risks:**

- If Redis is unavailable at startup: **fail fast** (not degrade gracefully) — a missing Redis means the idempotency guarantee is broken. Document this in `config.py` with a clear `RuntimeError`.
- `model_dump()` on `PendingDecision` must serialise `datetime` as ISO 8601 strings — use `model_dump(mode="json")` to ensure JSON-safe output.
- `fakeredis` may not support all Redis commands used — prefer `GETSET`, `SET EX`, and `TTL` which are universally supported.

**Definition of done:**

- All 6 acceptance criteria pass in CI (using `fakeredis`).
- `docker compose up` starts agent + Redis; idempotency verified with two identical `curl` calls.
- `REDIS_URL` documented in `.env.example`.

**Rollout:** Deploy with Redis service running. Set `REDIS_URL`. In-flight in-memory pending entries are not migrated (acceptable — any open approvals must be re-submitted).

**Backout:** Revert to commit before this PR. In-memory pending dict is restored. Note: any pending items stored in Redis during the PR window are ignored.

---

## PR-2 · Output Guard [P0]

**Scope:** Add `_guard_output()` to `AgentService` to scan LLM-generated draft text for leaked
secrets and unlisted URLs, and enforce a hard confidence floor before returning results to callers.

**Files touched:**

- `app/guardrails/` *(new directory)*
- `app/guardrails/__init__.py` *(new)*
- `app/guardrails/output_guard.py` *(new)* — `OutputGuard.scan(draft_text, confidence) -> GuardResult`
- `app/agent.py` — call `OutputGuard.scan()` after `llm_client.run_agent()`; handle `GuardResult`
- `app/config.py` — add `output_guard_enabled: bool = True`, `url_allowlist: list[str] = []`, `output_url_behavior: Literal["strip", "reject"] = "strip"`
- `.env.example` — document `OUTPUT_GUARD_ENABLED`, `URL_ALLOWLIST`, `OUTPUT_URL_BEHAVIOR`

**Secret patterns to scan:**

```python
SECRET_PATTERNS = [
    re.compile(r'sk-ant-[a-zA-Z0-9\-]{20,}'),
    re.compile(r'lin_api_[a-zA-Z0-9]{20,}'),
    re.compile(r'Bearer\s+[a-zA-Z0-9+/=]{20,}'),
]
```

**Acceptance criteria:**

1. A draft containing `sk-ant-aBcD1234567890abcde` causes the endpoint to return HTTP 500 with `"Internal: output guard blocked response"` (no secret leaked in `detail`).
2. A draft containing `lin_api_XyZ1234567890abcde` is blocked with HTTP 500.
3. A draft containing `https://evil.example.com/link` is stripped when `OUTPUT_URL_BEHAVIOR=strip` and `evil.example.com` is not in `URL_ALLOWLIST`.
4. A draft containing `https://kb.example.com/tips` passes unmodified when `kb.example.com` is in `URL_ALLOWLIST`.
5. A `ClassificationResult` with `confidence=0.3` overrides the proposed action to `flag_for_human` (sets `risky=True`, `risk_reason="confidence below safety floor"`) regardless of category.
6. `OUTPUT_GUARD_ENABLED=false` disables all checks; draft text passes through unmodified.

**Tests required:**

- `tests/test_output_guard.py`: each secret pattern; URL allowlist pass/fail; confidence gate at 0.3, 0.5, 0.85; guard disabled.
- Add 3 eval cases to `eval/cases.jsonl` with `"expected_guard": "output_blocked"` to confirm guard triggers.

**Risks:**

- `Bearer` regex may match long Base64 strings in legitimate support messages. Require minimum 20 chars after `Bearer ` and test against real billing messages before deploying.
- `URL_ALLOWLIST` defaults to empty — this blocks **all** URLs in drafts until the list is configured. Document prominently: set `URL_ALLOWLIST=` to your KB domain before enabling the guard.
- HTTP 500 on output guard hit may confuse n8n retry logic — ensure the error `detail` does not include the matched secret pattern.

**Definition of done:**

- All 6 acceptance criteria pass.
- `OUTPUT_GUARD_ENABLED`, `URL_ALLOWLIST`, `OUTPUT_URL_BEHAVIOR` in `.env.example` with a usage comment.

**Rollout:** Set `OUTPUT_GUARD_ENABLED=true` and configure `URL_ALLOWLIST`. Monitor logs for `output_guard_redacted` events in the first 24 h and expand the allowlist as needed.

**Backout:** Set `OUTPUT_GUARD_ENABLED=false` — no code change required.

---

## PR-3 · Tool Registry [P0]

**Scope:** Replace the hardcoded `create_ticket()` + `send_reply()` calls in `execute_action()`
with a `TOOL_REGISTRY` dict lookup so new tools can be added without modifying dispatch logic.

**Files touched:**

- `app/tools/__init__.py` — define `TOOL_REGISTRY: dict[str, Callable[[dict, str | None], dict]]`; define internal `_create_ticket_and_reply()` wrapper that calls existing stubs
- `app/agent.py` — `execute_action()` looks up `TOOL_REGISTRY[action.tool]`; raises `ValueError` on unknown tool name → HTTP 500

**Handler signature contract:**

```python
ToolHandler = Callable[[dict[str, Any], str | None], dict[str, Any]]
# (payload, user_id) -> result_dict
```

**Acceptance criteria:**

1. `execute_action()` contains no `if action.tool ==` or `elif action.tool ==` branches.
2. Calling `execute_action()` with `action.tool = "nonexistent_tool"` raises `ValueError` (surfaces as HTTP 500).
3. Adding a new tool requires exactly two changes: write the handler function; add one entry to `TOOL_REGISTRY`. No other files change.
4. All existing tests pass without modification.

**Tests required:**

- `tests/test_tool_registry.py`: known tool dispatches correctly; unknown tool raises; registry is a `dict` with correct type annotation.
- CI: `grep -r "action.tool ==" app/agent.py` returns no matches.

**Risks:**

- Tool handlers currently have inconsistent signatures (`create_ticket(payload)` vs `send_reply(user_id, text)`). The `_create_ticket_and_reply()` wrapper in `__init__.py` absorbs this inconsistency — do not change the existing stub signatures.
- Import cycle: `app/tools/__init__.py` imports from `ticketing.py` and `messenger.py` which import nothing from `app/tools/__init__.py` — safe.

**Definition of done:**

- All 4 acceptance criteria pass.
- `TOOL_REGISTRY` has a `dict[str, ToolHandler]` type annotation.

**Rollout:** Drop-in refactor; no env changes. Deploy with normal blue/green switch.

**Backout:** Revert PR. No state or configuration affected.

---

## PR-4 · n8n Workflow Artifact [P0]

**Scope:** Commit importable n8n workflow JSON files covering the full triage-and-approval loop,
and document them in `docs/N8N.md`.

**Files touched:**

- `n8n/` *(new directory)*
- `n8n/workflow_triage.json` *(new)* — Triage workflow (Telegram Trigger → POST /webhook → approval or log)
- `n8n/workflow_approval_callback.json` *(new)* — Approval Callback workflow (Telegram callback_query → POST /approve → log)
- `n8n/README.md` *(new)* — import instructions, credential setup, n8n version requirement
- `docs/N8N.md` *(create)* — full blueprint (see `docs/N8N.md`)

**n8n version requirement:** Pin to `n8nio/n8n:1.x` in `docker-compose.yml`. Document minimum version.

**Acceptance criteria:**

1. `n8n/workflow_triage.json` imports cleanly into a fresh n8n `1.x` instance without errors.
2. `n8n/workflow_approval_callback.json` imports cleanly.
3. After configuring the 4 required credentials (agent URL, Telegram token, approval chat ID, webhook secret), a real Telegram message produces a valid `POST /webhook` call.
4. A message that returns `status: "pending"` causes n8n to send a Telegram message with ✅ Approve and ❌ Reject inline buttons. Button `callback_data` encodes `approve:{pending_id}` or `reject:{pending_id}`.
5. Clicking ✅ Approve in Telegram triggers the Approval Callback workflow, which calls `POST /approve` and the action executes.
6. A failed `/webhook` call (HTTP 5xx) triggers the retry chain (max 3 attempts) and notifies the ops channel on final failure.

**Tests required:**

- `jq . n8n/workflow_triage.json > /dev/null` — valid JSON.
- `jq . n8n/workflow_approval_callback.json > /dev/null` — valid JSON.
- Manual E2E test documented in PR description: Telegram message → agent → Telegram reply received; billing message → approval buttons → approve → action executed.

**Risks:**

- n8n workflow JSON format changes between versions — pin n8n version in `docker-compose.yml`.
- Telegram `callback_data` is limited to 64 bytes: `approve:` (8 chars) + `pending_id` (32 chars) = 40 chars. Fits. Do not embed full JSON in `callback_data`.
- The `callback_query` from Telegram must be answered with `answerCallbackQuery` within 30 s or the spinner never disappears. Handle this as the first node in the Approval Callback workflow.

**Definition of done:**

- Workflows pass manual E2E test in a local Docker environment (`docker compose up`).
- `docs/N8N.md` documents every node, all credentials, and all configuration points.

**Rollout:** Import workflows into n8n, set credentials, activate workflows.

**Backout:** Deactivate n8n workflows. Agent continues to function standalone via direct HTTP.

---

## PR-5 · Linear API Integration [P1]

**Scope:** Replace `create_ticket()` stub with a real Linear GraphQL mutation that creates an issue
and returns the issue ID and URL.

**Files touched:**

- `app/integrations/` *(new directory)*
- `app/integrations/__init__.py` *(new)*
- `app/integrations/linear.py` *(new)* — `LinearClient.create_issue(title, description, priority, team_id) -> dict`
- `app/tools/ticketing.py` — import and call `LinearClient.create_issue()`; return `{"ticket_id": issue_id, "url": issue_url, "status": "created"}`
- `app/config.py` — `linear_api_key: str | None = None`, `linear_team_id: str | None = None`
- `.env.example` — document `LINEAR_API_KEY`, `LINEAR_TEAM_ID`

**Linear GraphQL mutation:**

```graphql
mutation CreateIssue($title: String!, $description: String, $priority: Int, $teamId: String!) {
  issueCreate(input: {
    title: $title
    description: $description
    priority: $priority
    teamId: $teamId
  }) {
    success
    issue { id identifier url }
  }
}
```

**Priority mapping:**

| Urgency | Linear priority int |
|---------|---------------------|
| `critical` | 1 (Urgent) |
| `high` | 2 (High) |
| `medium` | 3 (Medium) |
| `low` | 4 (Low) |

**Acceptance criteria:**

1. `POST /webhook` with a `gameplay_question` message (auto-executed, low risk) creates a Linear issue in the configured team.
2. `action_result.ticket.ticket_id` matches the Linear issue identifier (e.g., `ENG-42`).
3. `action_result.ticket.url` is a valid Linear issue URL (e.g., `https://linear.app/team/issue/ENG-42`).
4. Missing `LINEAR_API_KEY` at startup logs a `WARNING`; stub fallback (`TKT-*`) is used without crashing.
5. Linear API HTTP 429 is caught, logged as `WARNING`, and surfaces as HTTP 503 to the caller.
6. Linear API HTTP 4xx (e.g., invalid team ID) surfaces as HTTP 500 with a safe error message.

**Tests required:**

- `tests/test_linear_integration.py`: mock `httpx.Client.post()`; verify correct GraphQL mutation body; handle 429 → 503; handle 4xx → 500; missing API key → stub fallback.
- Update `tests/test_approval_flow.py` to mock the Linear call.

**Risks:**

- Linear uses GraphQL, not REST. Use `httpx` with a hardcoded mutation string. Do not generate a full client library.
- Required Linear token scopes: `issues:create`, `issues:read`. Document in `n8n/README.md` and `.env.example`.
- Linear does not deduplicate issues — ensure `message_id` dedup (PR-1) is active before this PR ships to avoid duplicate tickets from retries.

**Definition of done:**

- All 6 acceptance criteria pass.
- Manual smoke test: real Linear issue created from a local `curl` test run.

**Rollout:** Set `LINEAR_API_KEY` and `LINEAR_TEAM_ID`. Stub fallback is automatic if keys are absent.

**Backout:** Unset `LINEAR_API_KEY` — stub returns `TKT-*` with no code change.

---

## PR-6 · Telegram Bot + Inline Approval Buttons [P1]

**Scope:** Replace `send_reply()` stub with real Telegram message delivery; send approval-notification
messages with ✅ / ❌ inline buttons when an action requires human approval.

**Files touched:**

- `app/integrations/telegram.py` *(new)* — `TelegramClient`: `send_message(chat_id, text)`, `send_approval_request(chat_id, pending_id, draft, reason) -> str` (returns `message_id`)
- `app/tools/messenger.py` — import and call `TelegramClient.send_message()`; fall back to stub if token absent
- `app/agent.py` — after `store.put_pending()`, call `TelegramClient.send_approval_request()` to notify approval channel
- `app/config.py` — `telegram_bot_token: str | None = None`, `telegram_approval_chat_id: str | None = None`
- `.env.example` — document `TELEGRAM_BOT_TOKEN`, `TELEGRAM_APPROVAL_CHAT_ID`

**Inline button `callback_data` format:**

```
approve:{pending_id}    (e.g., "approve:a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4")
reject:{pending_id}
```

Max 64 bytes per Telegram spec. `approve:` (8) + 32-char hex = 40 bytes. Safe.

**Approval message format (sent to `TELEGRAM_APPROVAL_CHAT_ID`):**

```
🔔 Approval Required

Category: billing | Urgency: high
Reason: category 'billing' requires approval

Draft reply:
"Thanks for reporting this payment issue..."

[✅ Approve] [❌ Reject]
```

**Acceptance criteria:**

1. `POST /webhook` with a low-risk message (`gameplay_question`) sends a Telegram reply to `metadata.chat_id`.
2. `POST /webhook` with `status: "pending"` sends a Telegram message to `TELEGRAM_APPROVAL_CHAT_ID` with two inline buttons.
3. Button `callback_data` contains the `pending_id` in the `approve:{id}` / `reject:{id}` format.
4. Missing `TELEGRAM_BOT_TOKEN` logs a `WARNING`; stub fallback (`"queued"`) is used without crashing.
5. Telegram API HTTP 429 is caught, logged as `WARNING`; does not surface as agent HTTP error (fire-and-forget delivery).
6. Absent `metadata.chat_id` (non-Telegram channel) is handled gracefully — no exception.

**Tests required:**

- `tests/test_telegram_integration.py`: mock `httpx.AsyncClient`; verify `sendMessage` payload; verify `reply_markup` for approval; handle 429; handle absent `chat_id`.

**Risks:**

- Telegram's `callback_query` from inline button clicks must be answered within 30 s via `answerCallbackQuery` — this is handled in the n8n Approval Callback Workflow (PR-4), not in the agent.
- Do not register a Telegram webhook in the agent (`setWebhook`) — all Telegram event handling lives in n8n. The agent only sends messages via the Bot API.
- `metadata.chat_id` may be absent if the webhook caller is not Telegram. Guard with `metadata.get("chat_id")`.

**Definition of done:**

- Manual E2E: Telegram message → agent → Telegram reply received in same chat.
- Approval flow: billing message → pending → approval buttons appear in approval chat.

**Rollout:** Set `TELEGRAM_BOT_TOKEN`. Configure `TELEGRAM_APPROVAL_CHAT_ID` to a private group. Register n8n Telegram webhook with `setWebhook` API call (done in n8n setup, not in agent code).

**Backout:** Unset `TELEGRAM_BOT_TOKEN` — stub returns `"queued"` with no code change.

---

## PR-7 · Webhook Signature Verification + Rate Limiting [P1]

**Scope:** Add HMAC-SHA256 signature verification middleware for all inbound `/webhook` calls, and a
Redis sliding-window rate limiter keyed by `user_id`.

**Files touched:**

- `app/middleware/` *(new directory)*
- `app/middleware/__init__.py` *(new)*
- `app/middleware/signature.py` *(new)* — `SignatureMiddleware`: reads `X-Webhook-Signature`, verifies with `hmac.compare_digest()`
- `app/middleware/rate_limit.py` *(new)* — `RateLimitMiddleware`: Redis sliding window counter per `user_id`
- `app/main.py` — register `SignatureMiddleware` first, then `RateLimitMiddleware`, then existing `request_id_middleware`
- `app/config.py` — `webhook_secret: str | None = None`, `rate_limit_rpm: int = 10`, `rate_limit_burst: int = 3`
- `.env.example` — document `WEBHOOK_SECRET`, `RATE_LIMIT_RPM`, `RATE_LIMIT_BURST`

**Signature algorithm:**

```python
import hmac, hashlib
expected = "sha256=" + hmac.new(
    WEBHOOK_SECRET.encode(),
    raw_body_bytes,
    hashlib.sha256
).hexdigest()
ok = hmac.compare_digest(expected, request.headers.get("X-Webhook-Signature", ""))
```

**Rate limit Redis key:** `ratelimit:{user_id}` — sliding window with `INCR` + `EXPIRE`.

**Acceptance criteria:**

1. `POST /webhook` without `X-Webhook-Signature` returns HTTP 401 when `WEBHOOK_SECRET` is set.
2. `POST /webhook` with a correct signature returns the normal response.
3. `POST /webhook` with a tampered body + original signature returns HTTP 401. The comparison must use `hmac.compare_digest()` — verify in code review.
4. When `WEBHOOK_SECRET` is unset, signature check is skipped (development mode).
5. Sending 11 requests within 60 s from the same `user_id` returns HTTP 429 on the 11th.
6. Two different `user_id` values have independent rate limit counters.

**Tests required:**

- `tests/test_middleware.py`: signature valid/invalid/absent/WEBHOOK_SECRET-unset; rate limit hit/not hit; two users independent. Use `fakeredis` for rate limit tests.

**Risks:**

- Raw request body must be consumed before routing. Use a Starlette `BaseHTTPMiddleware` or `Request.body()` approach — not a FastAPI dependency, which runs after body parsing.
- If Redis is unavailable, rate limiting must **degrade gracefully** (log warning, allow request). Do not block traffic on Redis failure.
- HMAC check applies to **all** routes that include `/webhook` — apply middleware selectively or check path in middleware body.

**Definition of done:**

- All 6 acceptance criteria pass.
- Code review confirms `hmac.compare_digest()` is used (not `==`).
- `WEBHOOK_SECRET`, `RATE_LIMIT_RPM`, `RATE_LIMIT_BURST` in `.env.example`.

**Rollout:** Set `WEBHOOK_SECRET` in agent `.env` and in n8n HTTP Request node credentials (under "Header Auth"). Deploy. Verify n8n sends the correct signature on first call.

**Backout:** Unset `WEBHOOK_SECRET` — signature check is skipped automatically. Set `RATE_LIMIT_RPM=99999` to effectively disable rate limiting.

---

## PR-8 · Eval Dataset Expansion + Guard Metric [P1]

**Scope:** Expand `eval/cases.jsonl` to 25 labelled cases and update `eval/runner.py` to report
guard blocks as a separate metric, distinct from classification accuracy.

**Files touched:**

- `eval/cases.jsonl` — expand from 6 to 25 cases
- `eval/runner.py` — add `guard_blocks` counter; `guard_block_rate` field; per-label accuracy table
- `eval/results/` *(new directory)* — `last_run.json` committed after each passing run

**Required case distribution:**

| Category | Min cases |
|----------|-----------|
| `billing` | 5 |
| `account_access` | 4 |
| `bug_report` | 5 |
| `cheater_report` | 3 |
| `gameplay_question` | 4 |
| `other` | 1 |
| Injection cases (`expected_guard: "input_blocked"`) | 2 |
| Legal-keyword cases | 1 |

**Case schema:**

```json
{
  "id": 1,
  "text": "...",
  "expected_category": "billing",
  "expected_urgency": "high",
  "expected_guard": null
}
```

Injection cases: set `"expected_guard": "input_blocked"` and `"expected_category": null`.

**Eval output schema:**

```json
{
  "total": 25,
  "correct": 21,
  "guard_blocks": 2,
  "accuracy": 0.88,
  "guard_block_rate": 1.0,
  "per_label_accuracy": { "billing": 1.0, "bug_report": 0.8, "..." : "..." }
}
```

**Acceptance criteria:**

1. `eval/cases.jsonl` contains exactly 25 cases with the distribution above.
2. Injection cases have `"expected_guard": "input_blocked"` and are counted in `guard_blocks`, not in `correct` or `total` for accuracy.
3. `eval/runner.py` output includes `total`, `correct`, `guard_blocks`, `accuracy`, `guard_block_rate`, `per_label_accuracy`.
4. `guard_block_rate` is `1.0` for all cases with `expected_guard: "input_blocked"`.
5. `accuracy` ≥ 0.85 on classification cases (excluding guard-blocked cases from denominator).

**Tests required:**

- `tests/test_eval_runner.py`: mock `AgentService`; verify `guard_blocks` counted separately; verify accuracy excludes guard cases.
- Run full eval against live API at least once before merge; commit `eval/results/last_run.json`.

**Risks:**

- LLM accuracy on new edge cases may be below 0.85. If so, adjust the system prompt in `app/llm_client.py` and re-run before accepting.
- Guard-blocked cases must be detected from HTTP 400 responses — the runner must handle the 400 status code and match it to `expected_guard: "input_blocked"`.

**Definition of done:**

- 25 cases, all 5 acceptance criteria pass, `eval/results/last_run.json` committed with `accuracy ≥ 0.85`.

**Rollout:** No production changes. Run eval against staging or locally.

**Backout:** N/A — no production impact.

---

## PR-9 · Google Sheets Audit Log [P2]

**Scope:** After each completed action (executed, approved, or rejected), asynchronously append a row
to a configured Google Sheets spreadsheet as a human-readable audit trail.

**Files touched:**

- `app/integrations/sheets.py` *(new)* — `SheetsClient.append_log(entry: AuditLogEntry)`
- `app/schemas.py` — add `AuditLogEntry` Pydantic model
- `app/agent.py` — after `execute_action()` and after `approve()`, call `SheetsClient.append_log()` in a background thread (do not block response)
- `app/config.py` — `google_sheets_credentials_json: str | None = None`, `google_sheets_id: str | None = None`
- `.env.example` — document `GOOGLE_SHEETS_CREDENTIALS_JSON`, `GOOGLE_SHEETS_ID`

**Audit log columns (in order):**

| Column | Value | Source |
|--------|-------|--------|
| `timestamp` | UTC ISO 8601 | `datetime.now(UTC)` |
| `request_id` | Trace ID | `REQUEST_ID` ContextVar |
| `message_id` | Original webhook field | `WebhookRequest.message_id` |
| `user_id` | SHA-256 hash in production | `WebhookRequest.user_id` |
| `category` | Classification | `ClassificationResult.category` |
| `urgency` | Classification | `ClassificationResult.urgency` |
| `confidence` | Classification | `ClassificationResult.confidence` |
| `action` | Tool name | `ProposedAction.tool` |
| `status` | Outcome | `"executed"` / `"approved"` / `"rejected"` |
| `approved_by` | Reviewer or `"auto"` | `ApproveRequest.reviewer` |
| `ticket_id` | From action result | `action_result.ticket.ticket_id` |
| `latency_ms` | End-to-end | `time.monotonic()` diff |
| `cost_usd` | Estimated LLM cost | From `response.usage` tokens |

**Acceptance criteria:**

1. After `POST /webhook` (auto-executed), a row appears in the spreadsheet within 10 s.
2. After `POST /approve`, a row appears with `status=approved` and `approved_by=<reviewer>`.
3. The Sheets write runs in a background thread — the `/webhook` response latency does not increase.
4. Missing `GOOGLE_SHEETS_CREDENTIALS_JSON` logs a `WARNING` and disables Sheets logging without crashing.
5. Sheets API HTTP 429 is caught and logged as `WARNING`; does not surface as agent HTTP error.

**Tests required:**

- `tests/test_sheets_integration.py`: mock `google-api-python-client`; verify row structure; handle 429; handle missing credentials.

**Risks:**

- Google Sheets API quota: 300 writes/min per project. Under load, writes may be throttled — retry with backoff rather than batching for MVP simplicity.
- Service account credentials JSON contains a private key. Support both a file path and an inline JSON string in `GOOGLE_SHEETS_CREDENTIALS_JSON`. Never log the credentials.
- `user_id` must be hashed (`sha256(user_id).hexdigest()`) in the Sheets log, not stored in plaintext.

**Definition of done:**

- All 5 acceptance criteria pass.
- Manual test: real row appears in a test spreadsheet after a local `curl` run.

**Rollout:** Create a service account with Sheets edit access; share the spreadsheet with the service account email; set env vars.

**Backout:** Unset `GOOGLE_SHEETS_CREDENTIALS_JSON` — logging silently disabled.

---

## PR-10 · Docker Compose Full Stack + Demo Script [P2]

**Scope:** Produce a `docker-compose.yml` that starts the full stack (agent, Redis, n8n) with correct
networking and healthchecks, and a `scripts/demo.sh` that demonstrates 3 scenarios end-to-end.

**Files touched:**

- `docker-compose.yml` *(new or replace existing)*
- `Dockerfile` *(new or replace existing)*
- `scripts/demo.sh` *(new)* — 3 `curl` scenarios: gameplay (auto), billing (approval), injection (blocked)
- `.env.example` — verify all vars are documented
- `README.md` — add `docker compose up --build` quick-start section

**Docker services:**

| Service | Image | Internal port | Healthcheck |
|---------|-------|--------------|-------------|
| `agent` | Built from `Dockerfile` (Python 3.12-slim) | `8000` | `GET /health` |
| `redis` | `redis:7-alpine` | `6379` | `redis-cli ping` |
| `n8n` | `n8nio/n8n:1.x` | `5678` | `GET /healthz` |

All services share a Docker bridge network named `gdev`. n8n can reach the agent at `http://agent:8000`.

**Acceptance criteria:**

1. `docker compose up --build` starts all three services with no errors on a clean Linux/macOS machine.
2. `GET localhost:8000/health` returns `{"status": "ok"}`.
3. `bash scripts/demo.sh` runs all 3 scenarios and prints `PASS` or `FAIL` for each.
4. Demo scenario 1 (gameplay question, auto-executed): `status == "executed"`.
5. Demo scenario 2 (billing dispute): `status == "pending"` with a non-empty `pending_id`.
6. Demo scenario 3 (prompt injection): HTTP 400 `"Input failed injection guard"`.

**Tests required:**

- CI step: `docker compose up --build -d && sleep 10 && curl -f localhost:8000/health`.
- Manual `scripts/demo.sh` run documented in PR description.

**Risks:**

- n8n data volume must persist workflow imports — mount `./n8n/data:/home/node/.n8n`.
- Port conflicts on developer machines — allow overrides via `AGENT_PORT` and `N8N_PORT` env vars.

**Definition of done:**

- All 6 acceptance criteria pass on a clean machine.
- `docker compose down -v` leaves no orphan volumes.

**Rollout:** Developer tooling only. Production uses separate orchestration (Kubernetes, ECS).

**Backout:** N/A.

---

## Global Definition of Done

A PR is merged only when **all** of the following are true:

- [ ] All acceptance criteria for that PR pass in CI.
- [ ] New code has unit tests; no existing test is removed without justification.
- [ ] `eval/runner.py` accuracy ≥ 0.85 (does not regress from last committed `eval/results/last_run.json`).
- [ ] No new hardcoded values — all configurable items added to `app/config.py` and `.env.example`.
- [ ] `git grep -rn "sk-ant\|lin_api_\|Bearer " app/` returns no results.
- [ ] `docs/ARCHITECTURE.md` component status table is updated to reflect the merged state.
- [ ] The engineering review checklist in `docs/REVIEW_NOTES.md` was consulted before merge.

## Target Eval Metrics

| Metric | Target | Critical floor |
|--------|--------|----------------|
| Classification accuracy | > 0.85 | > 0.75 |
| Urgency accuracy | > 0.80 | > 0.70 |
| Guard block rate (injection cases) | 1.00 | 1.00 |
| P50 latency | < 1.5 s | < 3 s |
| P95 latency | < 3 s | < 5 s |
| Cost per request | < $0.005 | < $0.01 |
