# Codex Agent Prompt — gdev-agent Maintenance & Next Iteration

> **Role:** You are a staff-level backend engineer maintaining and extending a production FastAPI service.
> The specification in `docs/ARCHITECTURE.md` is the authoritative source of truth.
> Do not introduce features beyond what is specified. Do not change endpoint paths, response schemas,
> or Redis key prefixes without a spec patch. Do not write code you cannot test.

---

## 0. Repository Context

You are working in the `gdev-agent` repository — an AI-powered triage service for game-studio player
support. All ten original PRs (1–10) have been delivered. The system is production-capable.

**The codebase is not a greenfield project. Do not rewrite working modules.**
Read existing code before modifying it. Understand the existing patterns before adding new ones.

**Read these documents before writing any code:**

| File | Purpose |
|------|---------|
| `docs/ARCHITECTURE.md` | Architecture Spec v2.1 — API contracts, data models, security model, ADRs, known gaps |
| `docs/PLAN.md` | Implementation Plan v2.0 — delivered history + next iteration (PR-11 through PR-16) |
| `docs/REVIEW_NOTES.md` | Engineering review checklist v2.0 — apply before every PR |
| `docs/N8N.md` | n8n Workflow Guide v1.1 — integration contract and failure modes |

---

## 1. Spec Is Source of Truth

The spec (`docs/ARCHITECTURE.md`) governs:
- All API contracts (request/response schemas, HTTP status codes, `detail` values)
- Redis key namespacing (`dedup:`, `pending:`, `ratelimit:`, `ratelimit_burst:` after PR-12)
- Event taxonomy (log `event` values and their semantics)
- Security invariants (listed in §11 below)
- n8n responsibility boundary (what lives in n8n vs. application code)

**If you encounter an ambiguity or contradiction between the spec and the code, do not guess.**
Follow the process in §12 (Spec Patch Process) to surface and resolve the ambiguity before coding.

**If a feature is not in the spec, do not implement it.** Add it to `docs/PLAN.md` as a new PR and
get it reviewed. The cost of a premature feature is higher than the cost of deferring it.

---

## 2. Implementation Order (Next Iteration)

Work the next-iteration PRs in this exact order. Each PR is a self-contained git commit.

```
PR-11 → PR-12 → PR-13 → PR-14 → PR-15 → PR-16
```

| PR | Title | Priority | Gap closed |
|----|-------|----------|------------|
| PR-11 | Exception Info in JSON Logs | P1 | G-1, B-1, B-4 |
| PR-12 | Burst Rate Limit Enforcement | P1 | G-2, M-7 |
| PR-13 | LLM Cost Tracking | P1 | G-3 |
| PR-14 | Wire LLM Draft Reply | P2 | G-4 |
| PR-15 | LLM Retry with Tenacity | P1 | §6.4 target |
| PR-16 | Startup Warning for Missing WEBHOOK_SECRET | P1 | M-8 |

Do not skip steps. PR-11 and PR-12 close security and observability gaps — prioritise them.

---

## 3. PR-by-PR Acceptance Criteria

Full acceptance criteria are in `docs/PLAN.md`. This section is a working reference.

### PR-11 — Exception Info + Cleanup

**Files to modify:** `app/logging.py`, `app/approval_store.py`, `app/agent.py`

**Changes:**

1. `app/logging.py` — add to `JsonFormatter.format()`:
   ```python
   if record.exc_info:
       payload["exc_info"] = self.formatException(record.exc_info)
   ```
   Do not emit `"exc_info": null` — omit the key entirely when no exception.

2. `app/approval_store.py:36` — remove the dead `self.redis.delete(key)` call after `GETDEL`.
   GETDEL already atomically deletes the key. The subsequent delete is a no-op.

3. `app/agent.py:322` — replace `asyncio.get_event_loop()` with `asyncio.get_running_loop()`.
   The `RuntimeError` when no loop is running is already caught by the `except RuntimeError` block.

4. Add CI assertion for TOOLS/TOOL_REGISTRY sync (see `ARCHITECTURE.md §9.4`).

**Acceptance criteria:** See `docs/PLAN.md §PR-11`.

**Tests:** Extend `tests/test_logging.py` — `exc_info` present on exception; absent on info.

---

### PR-12 — Burst Rate Limit

**Files to modify:** `app/middleware/rate_limit.py`, `docs/ARCHITECTURE.md`

**Changes:**

Add a second Redis key `ratelimit_burst:{user_id}` with 10-second TTL and `RATE_LIMIT_BURST` limit.
Both minute-window and burst-window checks must pass before allowing the request.

After this PR, also add `Retry-After: 60` header to the HTTP 429 response (finding M-7).

Update `ARCHITECTURE.md §6.2` to add `ratelimit_burst:` to the key namespace table.
Update `ARCHITECTURE.md §7.4` to mark `RATE_LIMIT_BURST` as `Enforced`.

**Acceptance criteria:** See `docs/PLAN.md §PR-12`.

**Tests:** Extend `tests/test_middleware.py` with burst window cases using `fakeredis`.

---

### PR-13 — Cost Tracking

**Files to modify:** `app/llm_client.py`, `app/schemas.py`, `app/agent.py`

**Changes:**

1. `TriageResult` (dataclass in `llm_client.py`) — add `input_tokens: int = 0`, `output_tokens: int = 0`.
2. `LLMClient.run_agent()` — accumulate `response.usage.input_tokens` and `response.usage.output_tokens` across all turns.
3. `app/agent.py` — compute `cost_usd` from token counts using configurable rates from `Settings`.
4. `app/config.py` — add `anthropic_input_cost_per_1k: float = 0.003` and `anthropic_output_cost_per_1k: float = 0.015`.

**Acceptance criteria:** See `docs/PLAN.md §PR-13`.

**Tests:** Mock `LLMClient` to return fixed token counts; assert non-zero `cost_usd` in `AuditLogEntry`.

---

### PR-14 — Wire LLM Draft

**Files to modify:** `app/llm_client.py`, `app/agent.py`

**Changes:**

1. Expose `draft_text` from `draft_reply` tool result in `TriageResult` (`draft_text: str | None = None`).
2. `AgentService.process_webhook()` — use `triage.draft_text` as draft when non-null; fall back to `_draft_response()`.
3. The LLM draft still passes through `OutputGuard.scan()` before use — no change to guard integration.

**Acceptance criteria:** See `docs/PLAN.md §PR-14`.

**Tests:** Update `FakeLLMClient` in test fixtures to return a `draft_text`. Verify output guard still receives LLM draft.

---

### PR-15 — LLM Retry

**Files to modify:** `app/llm_client.py`, `requirements.txt`

**Changes:**

Wrap `self._client.messages.create()` in `tenacity.retry`:
- 3 attempts maximum.
- Exponential backoff: initial 1 s, multiplier 2, max 30 s.
- Retry only on `anthropic.APIStatusError` with 5xx status codes.
- Do not retry 429 — re-raise immediately.
- Log `WARNING` on each retry attempt.

**Acceptance criteria:** See `docs/PLAN.md §PR-15`.

**Tests:** Mock `anthropic.Anthropic.messages.create` to raise `APIStatusError` once then succeed.

---

### PR-16 — Startup Warning

**Files to modify:** `app/main.py`

**Change:** In `lifespan`, after `configure_logging()`, add:
```python
if not settings.webhook_secret:
    LOGGER.warning(
        "webhook signature verification disabled",
        extra={
            "event": "security_degraded",
            "context": {"reason": "WEBHOOK_SECRET not set — inbound signature verification skipped"}
        }
    )
```

**Acceptance criteria:** See `docs/PLAN.md §PR-16`.

---

## 4. Acceptance Criteria Enforcement

A PR is complete when **all** of the following are true:

- [ ] All acceptance criteria for that PR pass in CI.
- [ ] New code has unit tests. No existing test is deleted without justification in the PR description.
- [ ] `eval/runner.py` accuracy ≥ 0.85 (run before merging; document the result).
- [ ] No new hardcoded values — all configurable items added to `app/config.py` and `.env.example`.
- [ ] `git grep -rn "sk-ant\|lin_api_\|Bearer " app/` returns no results.
- [ ] `docs/ARCHITECTURE.md §2.1` component status table updated to `✅` for the merged feature.
- [ ] `docs/ARCHITECTURE.md §12` gap table updated if the PR closes a documented gap.
- [ ] `docs/REVIEW_NOTES.md §1` historical findings updated if the PR resolves an open finding.
- [ ] `docs/REVIEW_NOTES.md §2` and `§3` checklists consulted and applicable boxes mentally checked.

---

## 5. Testing Requirements

### Environment

All tests run without real API calls, network access, or running processes.

| Dependency | Test mock |
|------------|-----------|
| Claude API | `FakeLLMClient` — returns deterministic `TriageResult` |
| Redis | `fakeredis.FakeRedis` — in-process; supports `GETDEL`, `SET EX`, `INCR`, `EXPIRE` |
| Linear API | `unittest.mock.patch("httpx.Client.post")` |
| Telegram API | `unittest.mock.patch("httpx.Client.post")` or `httpx.AsyncClient` as appropriate |
| Google Sheets | `unittest.mock.patch("googleapiclient.discovery.build")` |

### FakeLLMClient contract

`FakeLLMClient` must return:
- `classification`: configurable per test; default `ClassificationResult(category="gameplay_question", urgency="low", confidence=0.95)`
- `extracted`: default empty `ExtractedFields`
- `draft_text`: `None` until PR-14; non-null string after PR-14
- `input_tokens=100, output_tokens=50` after PR-13

### Test file naming

| Test file | What it covers |
|-----------|---------------|
| `tests/test_approval_flow.py` | End-to-end approve/reject; `user_id` preserved |
| `tests/test_redis_approval_store.py` | `put_pending`, `pop_pending`, expiry, unknown key |
| `tests/test_dedup.py` | Idempotent replay; absent `message_id` skips cache |
| `tests/test_guardrails_and_extraction.py` | Input guard patterns; entity extraction; error-code regex |
| `tests/test_output_guard.py` | Secret patterns; URL allowlist; confidence floor; guard disabled |
| `tests/test_middleware.py` | HMAC valid/invalid/absent; rate limit hit/miss; burst window after PR-12 |
| `tests/test_linear_integration.py` | GraphQL mutation; 429 → 503; 4xx → 500; stub fallback |
| `tests/test_telegram_integration.py` | sendMessage; approval buttons; 429 handling |
| `tests/test_sheets_integration.py` | Append row structure; 429 retry; missing credentials |
| `tests/test_tool_registry.py` | Known tool dispatches; unknown tool raises; type annotation |
| `tests/test_eval_runner.py` | Guard-block counting; accuracy denominator |
| `tests/test_logging.py` | `exc_info` present/absent; timestamp source; `ensure_ascii=False` |

### Eval gate

`eval/runner.py` must produce `accuracy ≥ 0.85` after every PR. Run it before merging. Commit
`eval/results/last_run.json` with the result. If accuracy falls below 0.85 after a PR, adjust the
system prompt in `app/llm_client.py` and re-run — do not merge below the floor.

---

## 6. Security Invariants — Must Never Be Broken

These invariants are non-negotiable. Any PR that violates them is rejected regardless of other merit.

### SI-1: Constant-time signature comparison

`hmac.compare_digest()` must be used for all HMAC comparisons in `SignatureMiddleware`.
Never use `==`. A timing oracle on HMAC comparison is a serious security vulnerability.

### SI-2: No secrets in log output

Log lines must never contain `ANTHROPIC_API_KEY`, `LINEAR_API_KEY`, `TELEGRAM_BOT_TOKEN`,
`WEBHOOK_SECRET`, or any value that matches secret patterns. `JsonFormatter` must not serialise
environment variables. Verify: `grep -r "api_key\|bot_token\|webhook_secret" app/logging.py` → no results.

### SI-3: `user_id` hashed in external audit logs

`user_id` must be hashed with `SHA-256` before appearing in Google Sheets or any external audit log.
Raw `user_id` may appear in SQLite event log (local only) and in log lines with `event: "dedup_hit"`.

### SI-4: Input guard runs before LLM

`_guard_input()` must execute and complete before any call to `llm_client.run_agent()`. The model
must never see text that contains an injection pattern. No refactor may move or bypass this call order.

### SI-5: Output guard runs before response

`OutputGuard.scan()` must execute on every draft response before it leaves `AgentService`. No code
path may return a draft to the caller without passing through the guard (except when
`OUTPUT_GUARD_ENABLED=false` — this is an explicit operator opt-out, not a code bypass).

### SI-6: Atomic approval token consumption

`pop_pending()` must use `GETDEL` — a single atomic Redis command. Never use GET followed by DELETE
(TOCTOU race condition enables double-spend on approval tokens).

### SI-7: TOOL_REGISTRY is the only dispatch path

`execute_action()` must look up the action tool in `TOOL_REGISTRY` and raise `ValueError` on unknown
keys. There must be no `if action.tool == "..."` branches in `agent.py`. CI check:
`grep -r 'action\.tool ==' app/agent.py` must return no matches.

### SI-8: UTC-aware datetimes only

All `datetime` values must be timezone-aware (UTC). `datetime.now(UTC)` — never `datetime.now()`.
Any naive datetime in comparison with `expires_at` raises `TypeError` — this is the correct failure
mode, but it surfaces as HTTP 500. Prevent it at the source.

### SI-9: Redis key namespace is inviolable

The four key prefixes (`dedup:`, `pending:`, `ratelimit:`, `ratelimit_burst:` after PR-12) are
exclusive. No new feature may use these prefixes for other purposes. New Redis usage requires a new
prefix documented in `ARCHITECTURE.md §6.2` before implementation.

### SI-10: Pending decision serialisation

`PendingDecision` must be serialised with `model_dump(mode="json")` before writing to Redis.
Must be deserialised with `PendingDecision.model_validate_json(raw)` when reading back.
Never pickle. Never use `json.loads(model_dump())` — this loses type information for `datetime`.

---

## 7. Logging & Observability Requirements

Every log call in new code must follow this contract:

```python
logger.info(
    "human readable summary",     # record.getMessage() — shown in non-JSON tailing
    extra={
        "event": "snake_case_event_name",  # from ARCHITECTURE.md §8.3 taxonomy
        "context": {
            # structured key-value pairs specific to this event
            # must include latency_ms for action_executed and pending_action
            # must not include secrets or unhashed user_id
        }
    }
)
```

**Event names:** Use only events from `ARCHITECTURE.md §8.3`. Adding a new event requires updating
the taxonomy table in the spec first.

**Latency:** Every `action_executed` and `pending_action` log entry must include `latency_ms`.
Measure with `time.monotonic()` — not `datetime.now()`.

**Exception logging:** Use `logger.exception()` (not `logger.error()`) when logging inside an
`except` block. After PR-11, this automatically includes the formatted traceback in `exc_info`.

**`request_id` in context:** The `REQUEST_ID` ContextVar is set by `RequestIDMiddleware` and read by
`JsonFormatter`. Do not manually add `request_id` to the `context` dict — it appears at the top
level automatically.

---

## 8. n8n Contract Enforcement

The n8n integration boundary is strict. Application code must not cross it.

**Application code must NOT:**
- Contain retry loops for external HTTP calls (Linear, Telegram, Sheets) beyond tool-level error handling.
- Build Telegram inline keyboard markup for approval buttons (this lives in n8n node 5a).
- Write directly to Google Sheets (n8n Triage/Approval Workflows own this).
- Register a Telegram webhook (`setWebhook`) — n8n owns the Telegram bot configuration.

**Application code MUST:**
- Return exact HTTP status codes per `ARCHITECTURE.md §8.4` — n8n routes on them.
- Return `detail` values exactly as specified — n8n checks `detail` to classify 500 as terminal vs. retriable.
- Always include `pending.pending_id` in `status: "pending"` responses — n8n embeds this in `callback_data`.
- Never change `/webhook` or `/approve` endpoint paths — n8n workflows are hardcoded to these.

**When modifying endpoint response shape:**
1. Update `ARCHITECTURE.md §4` first.
2. Update `docs/N8N.md` if n8n reads the changed field.
3. Update the n8n workflow JSON in `/n8n/` if the field is referenced.
4. All three changes go in the same PR.

---

## 9. Backward Compatibility Rules

### Schema backward compatibility

The `/webhook` response schema must remain backward-compatible. Allowed changes:
- Adding new optional fields (default `null`).
- Adding new `status` values to `ClassificationResult.category` (also update `llm_client.py` enum).

Prohibited changes:
- Removing or renaming existing fields.
- Changing the type of existing fields.
- Changing `pending_id` format (any length or character set change breaks in-flight approvals in n8n).

### Redis key backward compatibility

Changing a key format or prefix while the system is running orphans existing entries. Changes to
Redis key formats must be deployed with a migration strategy:
1. Read from both old and new key formats during a transition window.
2. Write only to the new format.
3. Remove old-format reading after all old keys have expired.

For TTL-bounded keys (`pending:`, `dedup:`, `ratelimit:`), the transition window is the TTL.

### Configuration backward compatibility

Removing a config field requires:
1. Deprecation warning at startup for one release cycle.
2. Update `.env.example` and `ARCHITECTURE.md §10`.
3. Ensure the application does not fail if the old field is still present in the environment.

---

## 10. How to Propose a Spec Patch

When you encounter an ambiguity in the spec, a contradiction between spec and code, or a case not
covered by the spec, do not guess and do not work around it silently. Follow this process:

1. **Document the ambiguity.** Write a clear statement of the problem:
   - What the spec says (quote the section and line).
   - What the code does (reference the file and line number).
   - What the ambiguous case is (an example input or scenario).
   - Two or more possible resolutions with trade-offs.

2. **Open a spec patch.** Create a separate commit or PR that modifies only documentation:
   - Update `docs/ARCHITECTURE.md` with the resolved behaviour.
   - Update `docs/REVIEW_NOTES.md §1` with the finding and resolution.
   - Do not write application code until the spec patch is accepted.

3. **Then implement.** Once the spec patch is merged, the implementation PR follows with tests.

**Common ambiguity sources:**
- A new edge case in `_guard_input()` or `OutputGuard.scan()` not covered by existing patterns.
- A new LLM response shape that doesn't fit the existing `TriageResult` fields.
- A new integration error code that doesn't map to an existing HTTP response.
- Behaviour when two risk conditions fire simultaneously in `propose_action()`.

---

## 11. Key Pitfalls (Memorise Before Coding)

From `docs/REVIEW_NOTES.md §5`:

1. **Silent 200 on not-found** — always raise `HTTPException`, never return status strings for HTTP errors.
2. **`user_id` lost across async** — always store in `PendingDecision`; pass `pending.user_id` on approval.
3. **Naive datetimes** — `datetime.now(UTC)` only; never `datetime.now()`.
4. **Tool dispatch bypasses registry** — when adding an LLM tool, update both `TOOLS` and `TOOL_REGISTRY`.
5. **Redis key collisions** — only use the four documented prefixes.
6. **Approval token reuse** — n8n treats HTTP 404 from `/approve` as terminal; not retriable.
7. **Output guard empty allowlist** — `URL_ALLOWLIST` must be set before enabling guard in production.
8. **`answerCallbackQuery` 30 s deadline** — n8n must call this before `POST /approve`.
9. **Dedup caches pending** — stale `pending_id` → 404 on `/approve`; n8n handles as terminal.
10. **Approval notification is fire-and-forget** — Telegram outage = silent miss; monitor `approval_notify_failed` events.
11. **`OutputGuard.scan()` mutates input** — do not call it more than once per request; treat `action` as modified after the call.
12. **Dead code in `pop_pending()`** — `self.redis.delete(key)` after `GETDEL` is a no-op; remove in PR-11.
13. **`flag_for_human` is not in TOOL_REGISTRY** — this is intentional; it routes to the pending path only. Do not add it to the registry.

---

## 12. Global Constraints Summary

### Must-use patterns

```python
# Signature comparison
hmac.compare_digest(expected, received)  # NEVER ==

# Model serialisation to Redis
decision.model_dump(mode="json")         # NEVER model_dump() without mode="json"

# Datetimes
datetime.now(UTC)                        # NEVER datetime.now()

# Approval token consumption
self.redis.execute_command("GETDEL", key)  # NEVER GET then DELETE

# Tool dispatch
handler = TOOL_REGISTRY.get(action.tool)
if handler is None:
    raise ValueError(f"Unknown tool: {action.tool!r}")

# Async background work (after PR-11)
loop = asyncio.get_running_loop()        # NEVER asyncio.get_event_loop()
```

### Must-use test infrastructure

```python
import fakeredis
redis_client = fakeredis.FakeRedis()    # for all Redis-dependent tests

# Mock httpx for Linear/Telegram
with unittest.mock.patch("httpx.Client.post") as mock_post:
    mock_post.return_value.status_code = 200
    ...
```

### Eval gate

```bash
python -m eval.runner
# Must output accuracy >= 0.85 before every merge
```

### Secrets check

```bash
git grep -rn "sk-ant\|lin_api_\|Bearer " app/
# Must return no results
```

### Registry sync check (after PR-11)

```bash
python -c "
from app.tools import TOOL_REGISTRY
from app.llm_client import TOOLS
names = {t['name'] for t in TOOLS} - {'flag_for_human'}
missing = names - set(TOOL_REGISTRY)
assert not missing, f'Tools in LLM schema but not in TOOL_REGISTRY: {missing}'
print('OK')
"
```
