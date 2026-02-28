# gdev-agent — Implementation Plan v2.0

_Updated: 2026-02-28 · All original PRs (1–10) are delivered and merged into `master`.
This document preserves their acceptance criteria as the historical contract,
then defines the next iteration of work._

---

## Part A — Delivered Work (PRs 1–10)

All ten planned PRs are implemented. The table below is the historical record.

| PR | Title | Priority | Status |
|----|-------|----------|--------|
| PR-1 | Redis Approval Store + Idempotency Dedup | P0 | ✅ Delivered |
| PR-2 | Output Guard | P0 | ✅ Delivered |
| PR-3 | Tool Registry | P0 | ✅ Delivered |
| PR-4 | n8n Workflow Artifacts | P0 | ✅ Delivered |
| PR-5 | Linear API Integration | P1 | ✅ Delivered |
| PR-6 | Telegram Bot + Inline Approval Buttons | P1 | ✅ Delivered |
| PR-7 | Webhook Signature Verification + Rate Limiting | P1 | ✅ Delivered |
| PR-8 | Eval Dataset Expansion + Guard Metric | P1 | ✅ Delivered |
| PR-9 | Google Sheets Audit Log | P2 | ✅ Delivered |
| PR-10 | Docker Compose Full Stack + Demo Script | P2 | ✅ Delivered |

Original acceptance criteria for each PR are preserved as comments in git history.
For the current API contract, data models, and security model, see `docs/ARCHITECTURE.md`.

---

## Priority Key (next iteration)

| Level | Meaning |
|-------|---------|
| **P0** | Correctness or security gap. Do not ship new features until resolved. |
| **P1** | Quality and observability. Ship before scaling traffic. |
| **P2** | Operational improvement. Ship iteratively. |

---

## Recommended Merge Order (Next Iteration)

```
PR-11 → PR-12 → PR-13 → PR-14 → PR-15 → PR-16
```

PR-11 (exc_info) and PR-12 (burst limiting) close documented spec gaps. PR-13 (cost tracking)
enables the stated measurable outcome. PR-14 (LLM draft wiring) improves response quality.
PR-15 and PR-16 are reliability improvements.

---

## PR-11 · Exception Info in JSON Logs [P1]

**Scope:** Add `exc_info` to `JsonFormatter.format()` so that `logger.exception()` calls emit a
non-null `exc_info` field containing the formatted traceback. Closes gap G-1 from
`docs/ARCHITECTURE.md §12`.

**Files touched:**

- `app/logging.py` — add `exc_info` field to the payload dict in `JsonFormatter.format()`

**Implementation:**

```python
if record.exc_info:
    payload["exc_info"] = self.formatException(record.exc_info)
```

**Acceptance criteria:**

1. Calling `logger.exception("something went wrong")` inside a `try/except` block produces a JSON
   log line with a non-null `exc_info` field containing the full formatted traceback.
2. `logger.info(...)` calls produce a log line with no `exc_info` field (not `null` — absent).
3. Multi-line tracebacks are serialised as a single escaped string (not split across JSON lines).
4. No regression on existing structured log tests.

**Tests required:**

- `tests/test_logging.py` (new or extend): assert `exc_info` present on exception log; absent on info log.

**Definition of done:**

- All 4 acceptance criteria pass.
- `docs/ARCHITECTURE.md §2.1` component status for `exc_info` updated to `✅`.
- `docs/REVIEW_NOTES.md §1` item N-2 updated to `✅ Resolved`.

---

## PR-12 · Burst Rate Limit Enforcement [P1]

**Scope:** Implement the `RATE_LIMIT_BURST` config field in `RateLimitMiddleware`. Currently the
field exists in `Settings` and `ARCHITECTURE.md` but is not enforced. Closes gap G-2.

**Files touched:**

- `app/middleware/rate_limit.py` — add burst window check alongside the existing per-minute check

**Algorithm:** Use a second Redis key `ratelimit_burst:{user_id}` with a 10-second TTL and a
`RATE_LIMIT_BURST` limit. Both checks must pass. The burst key uses the same INCR+EXPIRE pattern
as the minute key.

**Redis keys:**

| Key | TTL | Limit |
|-----|-----|-------|
| `ratelimit:{user_id}` | 60 s | `RATE_LIMIT_BURST_KEY` → RATE_LIMIT_RPM |
| `ratelimit_burst:{user_id}` | 10 s | `RATE_LIMIT_BURST` |

**Important:** Add `ratelimit_burst:` to the Redis key namespace table in `ARCHITECTURE.md §6.2`.

**Acceptance criteria:**

1. Sending `RATE_LIMIT_BURST + 1` requests within 10 s from the same `user_id` returns HTTP 429 on
   the last request.
2. Sending `RATE_LIMIT_BURST` requests in 10 s, then waiting 10 s, then sending `RATE_LIMIT_BURST`
   more requests succeeds (burst window resets).
3. `RATE_LIMIT_RPM` limit still applies: 11 requests spread over 60 s exceeds the per-minute cap.
4. Redis unavailable → both limits degrade gracefully (log warning, allow request).

**Tests required:**

- `tests/test_middleware.py` — extend with burst window test cases using `fakeredis`.

**Definition of done:**

- All 4 acceptance criteria pass.
- `ARCHITECTURE.md §7.4` updated to mark `RATE_LIMIT_BURST` as `Enforced`.
- `ARCHITECTURE.md §6.2` Redis namespace table updated with `ratelimit_burst:`.

---

## PR-13 · LLM Cost Tracking [P1]

**Scope:** Extract token counts from Claude API responses and populate `AuditLogEntry.cost_usd` with
an estimated cost. Closes gap G-3. Enables the stated measurable outcome "cost ≤ $0.01/request".

**Files touched:**

- `app/llm_client.py` — accumulate `input_tokens` and `output_tokens` across all turns; return with `TriageResult`
- `app/schemas.py` — add `input_tokens: int = 0`, `output_tokens: int = 0` to `TriageResult` (dataclass fields)
- `app/agent.py` — compute `cost_usd` from token counts; pass to `AuditLogEntry`

**Cost model (hardcoded to `claude-sonnet-4-6` defaults; update if model changes):**

```python
INPUT_COST_PER_1K  = 0.003   # USD per 1 000 input tokens
OUTPUT_COST_PER_1K = 0.015   # USD per 1 000 output tokens

cost_usd = (
    (input_tokens / 1000) * INPUT_COST_PER_1K +
    (output_tokens / 1000) * OUTPUT_COST_PER_1K
)
```

Add `ANTHROPIC_INPUT_COST_PER_1K` and `ANTHROPIC_OUTPUT_COST_PER_1K` to `Settings` with the above
defaults so operators can override if pricing changes.

**Acceptance criteria:**

1. After `POST /webhook`, the SQLite event log entry for `action_executed` includes non-zero
   `input_tokens` and `output_tokens`.
2. `AuditLogEntry.cost_usd` is non-zero and ≤ `0.01` for a typical 200-token input message.
3. Multi-turn conversations accumulate tokens across all turns (not just the last turn).
4. Token fields in `TriageResult` are present and non-zero in `FakeLLMClient` test mode (use a fixed
   value like `input_tokens=100, output_tokens=50`).

**Tests required:**

- `tests/test_agent.py` (new or extend): mock `LLMClient` returning non-zero tokens; assert `cost_usd` in `AuditLogEntry`.
- Update `FakeLLMClient` in test fixtures to return `input_tokens=100, output_tokens=50`.

**Definition of done:**

- All 4 acceptance criteria pass.
- `ARCHITECTURE.md §2.1` cost tracking row updated to `✅`.
- `ARCHITECTURE.md §12` gap G-3 resolved.

---

## PR-14 · Wire LLM Draft Reply into AgentService [P2]

**Scope:** Use the LLM's `draft_reply` tool output as the draft response instead of the hardcoded
`_draft_response()` strings. Keep `_draft_response()` as a fallback when the LLM does not call
`draft_reply`. Closes gap G-4.

**Files touched:**

- `app/llm_client.py` — expose `draft_text` from `draft_reply` tool result in `TriageResult`
- `app/schemas.py` — add `draft_text: str | None = None` to `TriageResult`
- `app/agent.py` — use `triage.draft_text` as the draft when non-null; fall back to `_draft_response()`

**Acceptance criteria:**

1. When Claude calls `draft_reply` with a non-empty `draft_text`, `process_webhook()` uses that text
   as `draft_response` (not the hardcoded fallback).
2. When Claude does not call `draft_reply`, `_draft_response()` fallback is used.
3. `draft_text` still passes through `OutputGuard.scan()` before use.
4. Eval harness `accuracy ≥ 0.85` is maintained after the change.

**Tests required:**

- Update relevant test fixtures so `FakeLLMClient` returns a `draft_text`.
- `tests/test_output_guard.py` — verify draft from LLM is still scanned by output guard.

**Definition of done:**

- All 4 acceptance criteria pass.
- `eval/runner.py` produces `accuracy ≥ 0.85` after the change.

---

## PR-15 · LLM Retry with Tenacity [P1]

**Scope:** Add retry logic inside `LLMClient.run_agent()` to handle transient Claude API failures
without surfacing every 5xx to n8n. Addresses the LLM retry gap in `ARCHITECTURE.md §6.4`.

**Files touched:**

- `app/llm_client.py` — wrap `self._client.messages.create()` in `tenacity.retry`
- `requirements.txt` — add `tenacity`

**Retry policy:**

```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    retry=retry_if_exception_type(anthropic.APIStatusError),
    reraise=True,
)
```

Only retry `5xx` status codes. Do not retry `429` — re-raise as a signal to surface as HTTP 503.

**Acceptance criteria:**

1. A transient `500` from the Claude API is retried up to 3 times with exponential backoff.
2. A `429` from the Claude API is not retried — raises immediately.
3. After 3 failed attempts, the original exception propagates (surfaces as HTTP 500 to n8n).
4. A successful attempt on the 2nd retry produces the normal response (no error to caller).

**Tests required:**

- `tests/test_llm_client.py` — mock `anthropic.Anthropic.messages.create` to fail once then succeed.

**Definition of done:**

- All 4 acceptance criteria pass.
- `ARCHITECTURE.md §6.4` updated to reflect retry implementation.

---

## PR-16 · Startup Warning for Missing WEBHOOK_SECRET [P1]

**Scope:** Log a `WARNING` at startup when `WEBHOOK_SECRET` is unset, so operators know the service
is running without inbound webhook authentication. Addresses gap M from Phase 1 review.

**Files touched:**

- `app/main.py` — add `WARNING` log in `lifespan` when `settings.webhook_secret` is `None` or empty

**Log format:**

```json
{
  "event": "security_degraded",
  "context": { "reason": "WEBHOOK_SECRET not set — inbound webhook signature verification disabled" }
}
```

**Acceptance criteria:**

1. Starting the agent without `WEBHOOK_SECRET` set emits a `WARNING`-level log with `event: "security_degraded"`.
2. Starting the agent with `WEBHOOK_SECRET` set emits no such warning.
3. The warning does not prevent startup.

**Tests required:**

- `tests/test_main.py` (new or extend): assert warning logged when secret absent; no warning when set.

**Definition of done:**

- All 3 acceptance criteria pass.
- `ARCHITECTURE.md §7.3` updated to document the startup warning.

---

## Global Definition of Done

A PR is merged only when **all** of the following are true:

- [ ] All acceptance criteria for that PR pass in CI.
- [ ] New code has unit tests; no existing test is removed without justification.
- [ ] `eval/runner.py` accuracy ≥ 0.85 (does not regress from last committed `eval/results/last_run.json`).
- [ ] No new hardcoded values — all configurable items added to `app/config.py` and `.env.example`.
- [ ] `git grep -rn "sk-ant\|lin_api_\|Bearer " app/` returns no results.
- [ ] `docs/ARCHITECTURE.md §2.1` component status table updated to reflect the merged state.
- [ ] The engineering review checklist in `docs/REVIEW_NOTES.md` was consulted before merge.
- [ ] `docs/ARCHITECTURE.md §12` gap table updated if the PR closes a gap.

---

## Target Eval Metrics

| Metric | Target | Critical floor |
|--------|--------|----------------|
| Classification accuracy | > 0.85 | > 0.75 |
| Urgency accuracy | > 0.80 | > 0.70 |
| Guard block rate (injection cases) | 1.00 | 1.00 |
| P50 latency | < 1.5 s | < 3 s |
| P95 latency | < 3 s | < 5 s |
| Cost per request | < $0.005 | < $0.01 |
