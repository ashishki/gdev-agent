# gdev-agent — Implementation Plan v3.0

_Updated: 2026-02-28 · All original PRs (1–16) are delivered and merged into `master`.
This document preserves their acceptance criteria as the historical contract,
then defines the next iteration of work._

---

## Part A — Delivered Work (PRs 1–16)

All sixteen planned PRs are implemented.

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
| PR-11 | Exception Info in JSON Logs | P1 | ✅ Delivered |
| PR-12 | Burst Rate Limit Enforcement | P1 | ✅ Delivered |
| PR-13 | LLM Cost Tracking | P1 | ✅ Delivered |
| PR-14 | Wire LLM Draft Reply | P2 | ✅ Delivered |
| PR-15 | LLM Retry with Tenacity | P1 | ✅ Delivered |
| PR-16 | Startup Warning for Missing WEBHOOK_SECRET | P1 | ✅ Delivered |

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
PR-21 → PR-17 → PR-18 → PR-19 → PR-20 → PR-22 → PR-23
```

PR-21 closes the pre-production KB URL blocker — ship it first. PR-17 and PR-18 close
observability and security gaps and must land before scaling traffic. PR-19 and PR-20 are
pure refactors with no behaviour change. PR-22 and PR-23 are architectural improvements
requiring more careful coordination.

---

## PR-17 · exc_info in Approval Notification Error Log [P1]

**Scope:** Add `exc_info=True` to `LOGGER.warning()` in `_notify_approval_channel()` so
that the exception traceback is captured when Telegram notification fails. Closes gap N-1.

**Files touched:**

- `app/agent.py`

**Change:**

```python
LOGGER.warning(
    "failed sending approval notification",
    extra={"event": "approval_notify_failed", "context": {"pending_id": pending.pending_id}},
    exc_info=True,   # ← add this
)
```

**Acceptance criteria:**

1. When `TelegramClient.send_approval_request()` raises, the log line includes a non-null
   `exc_info` field with the full formatted traceback.
2. When notification succeeds, no warning is logged.
3. Existing tests pass without modification.

**Tests required:**

- `tests/test_agent.py` — mock `TelegramClient.send_approval_request` to raise;
  assert log record has `exc_info`.

**Definition of done:**

- All 3 acceptance criteria pass.
- `docs/REVIEW_NOTES.md §1` item N-1 updated to `✅ Resolved`.

---

## PR-18 · /approve Endpoint Authentication [P1]

**Scope:** Protect `POST /approve` against unauthorized use. Any caller knowing a `pending_id`
can currently approve or reject an action. Add static secret header verification. Closes gap N-2.

**Files touched:**

- `app/config.py`
- `app/main.py` (add auth check in the `approve()` handler or a new middleware)
- `.env.example`

**New setting:**

```bash
APPROVE_SECRET=   # static shared secret; empty = auth skipped (WARNING logged at startup)
```

**Behavior:**

- When `APPROVE_SECRET` is set: `POST /approve` must include `X-Approve-Secret: <secret>`.
  Comparison uses `hmac.compare_digest()`. Mismatch → HTTP 401 `detail: "Unauthorized"`.
- When `APPROVE_SECRET` is not set: auth is skipped and a `WARNING` with
  `event: "security_degraded"` is logged at startup (same pattern as `WEBHOOK_SECRET`).

**Acceptance criteria:**

1. Correct `X-Approve-Secret` header → request proceeds normally (HTTP 200).
2. Incorrect or missing header when `APPROVE_SECRET` set → HTTP 401.
3. `APPROVE_SECRET` unset → request proceeds; startup emits `WARNING` with
   `event: "security_degraded"`.
4. Comparison uses `hmac.compare_digest()` — never `==`.

**Tests required:**

- `tests/test_middleware.py` or `tests/test_main.py` — cover all three scenarios above.

**Definition of done:**

- All 4 acceptance criteria pass.
- `ARCHITECTURE.md §7` updated to document the `/approve` auth model.
- `docs/REVIEW_NOTES.md §1` item N-2 updated to `✅ Resolved`.

---

## PR-19 · OutputGuard.scan() — Return Instead of Mutate [P2]

**Scope:** Eliminate the hidden side-effect where `scan()` mutates the caller's `action`
argument. Pure refactor — no behaviour change. Closes gap N-3.

**Files touched:**

- `app/guardrails/output_guard.py`
- `app/agent.py`

**Design:**

Add `action_override: ProposedAction | None = None` to `GuardResult`:

```python
@dataclass
class GuardResult:
    blocked: bool
    redacted_draft: str
    reason: str | None
    action_override: ProposedAction | None = None
```

In `scan()`, instead of mutating `action` in place, return the override:

```python
if confidence < 0.5:
    from copy import copy
    override = copy(action)
    override.tool = "flag_for_human"
    override.risky = True
    override.risk_reason = "confidence below safety floor"
    return GuardResult(blocked=False, redacted_draft=redacted, reason=None, action_override=override)
```

In `agent.py`, apply the override after the scan call:

```python
guard_result = self.output_guard.scan(draft_response, classification.confidence, action)
if guard_result.action_override is not None:
    action = guard_result.action_override
```

**Acceptance criteria:**

1. When `confidence < 0.5`, `guard_result.action_override` is a new `ProposedAction` with
   `tool="flag_for_human"`, `risky=True`. The original `action` is **not** mutated.
2. When `confidence >= 0.5`, `guard_result.action_override` is `None`. Original `action` not mutated.
3. All existing `test_output_guard.py` tests pass without modification.
4. New assertion in `test_output_guard.py` confirms input `action` object is not mutated.

**Definition of done:**

- All 4 acceptance criteria pass.
- `docs/REVIEW_NOTES.md §1` item N-3 updated to `✅ Resolved`.

---

## PR-20 · Narrow "act as" Injection Pattern [P2]

**Scope:** Replace `"act as"` in `INJECTION_PATTERNS` with `"act as if you"` to eliminate
false positives on legitimate player messages. Closes gap N-4.

**Files touched:**

- `app/agent.py` — `INJECTION_PATTERNS` tuple

**Change:**

```python
# Before
"act as",
# After
"act as if you",
```

**Acceptance criteria:**

1. `"act as if you are an admin"` → `_guard_input()` raises → HTTP 400.
2. `"I'd like you to act as a support agent"` → not blocked → HTTP 200.
3. `"Please act as a refund processor"` → not blocked → HTTP 200.
4. All existing injection guard test cases in `test_guardrails_and_extraction.py` still pass.

**Tests required:**

- `tests/test_guardrails_and_extraction.py` — add the 3 cases above.

**Definition of done:**

- All 4 acceptance criteria pass.
- `docs/REVIEW_NOTES.md §1` item N-4 updated to `✅ Resolved`.

---

## PR-21 · KB Base URL Configuration [P0 — pre-production blocker]

**Scope:** Replace hardcoded `https://kb.example.com` in `lookup_faq` with a configurable
`KB_BASE_URL` setting. Closes gap N-5. Users currently receive dead FAQ links — this is a
pre-production blocker.

**Files touched:**

- `app/config.py` — add `kb_base_url` field
- `app/llm_client.py` — use `self.settings.kb_base_url` in `_dispatch_tool`
- `.env.example` — add `KB_BASE_URL` with placeholder value

**New setting:**

```bash
KB_BASE_URL=https://kb.example.com  # Replace with real KB URL before going live
```

**Implementation:**

In `_dispatch_tool`, replace the hardcoded URL:

```python
if name == "lookup_faq":
    keywords = [str(item) for item in tool_input.get("keywords", [])][:3]
    return {
        "articles": [
            {"title": f"FAQ: {keyword}", "url": f"{self.settings.kb_base_url}/{keyword}"}
            for keyword in keywords
        ]
    }
```

`LLMClient.__init__` already stores `settings` — no constructor change needed.

**Acceptance criteria:**

1. When `KB_BASE_URL=https://support.mygame.com`, `lookup_faq` returns article URLs with
   the `https://support.mygame.com/` prefix.
2. When `KB_BASE_URL` is unset, default is `https://kb.example.com` (explicit placeholder).
3. `kb_base_url` is present in `Settings` and `.env.example`.
4. CI check: `git grep -n "kb.example.com" app/` → no matches (all occurrences use the setting).

**Tests required:**

- `tests/test_llm_client.py` — set `kb_base_url` in test settings; assert URL prefix in
  `lookup_faq` result.

**Definition of done:**

- All 4 acceptance criteria pass.
- `ARCHITECTURE.md` updated to document `KB_BASE_URL`.
- `docs/REVIEW_NOTES.md §1` item N-5 updated to `✅ Resolved`.

---

## PR-22 · Eliminate Dual Settings + Redis at Module Load [P2]

**Scope:** Remove `_middleware_settings = Settings()` and `redis.from_url(...)` from
module-level scope in `app/main.py`. Closes gap B-2.

**Files touched:**

- `app/main.py`
- `app/middleware/rate_limit.py`
- `app/middleware/signature.py`

**Context:**

Starlette requires `add_middleware()` at app construction time, before lifespan starts.
Current workaround creates a separate `Settings()` and Redis client at import time — two
instances, two connections, outside the dependency injection pattern used everywhere else.

**Design:**

Change middleware constructors to accept lazy factory callables instead of eager values:

```python
class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings_factory, redis_factory):
        super().__init__(app)
        self._settings_factory = settings_factory
        self._redis_factory = redis_factory
        self._settings = None
        self._redis = None

    def _get_settings(self):
        if self._settings is None:
            self._settings = self._settings_factory()
        return self._settings
```

In `main.py`, pass lambdas that read from `app.state` (populated during lifespan, before
the first request is served):

```python
app.add_middleware(
    RateLimitMiddleware,
    settings_factory=lambda: app.state.settings,
    redis_factory=lambda: app.state.redis,
)
```

**Acceptance criteria:**

1. No `Settings()` or `redis.from_url()` call at module import time.
2. Middleware uses the same `settings` and `redis` objects as `app.state`.
3. All existing middleware tests pass unchanged.
4. `python -c "import app.main"` does not raise if env vars are absent.

**Definition of done:**

- All 4 acceptance criteria pass.
- `docs/REVIEW_NOTES.md §1` item B-2 updated to `✅ Resolved`.

---

## PR-23 · Approval Notification Observability [P2]

**Scope:** Improve visibility into `_notify_approval_channel()` failures so that ops can
detect and manually recover from silent Telegram outages. Closes gap G-7 (minimal scope).

**Context:**

PR-17 adds `exc_info=True` to the failure log. The pending item is still in Redis and
`status: "pending"` is returned to n8n. If Telegram is down, no human sees the approval
request; the item expires silently at `APPROVAL_TTL_SECONDS`.

Full auto-recovery (polling endpoint + re-notification) requires a spec patch to
`ARCHITECTURE.md §4` and is out of scope for this PR.

**Files touched (documentation only):**

- `docs/N8N.md` — update §8.3
- `docs/ARCHITECTURE.md` — update §12 gap G-7 status

**Changes:**

1. `docs/N8N.md §8.3` — add monitoring guidance:
   > Monitor for `approval_notify_failed` log events in structured logs. When this event
   > fires, the pending item exists in Redis but no human was notified. Manual recovery:
   > re-send `POST /webhook` with the same message; this creates a new `pending_id`.
   > The original pending item will expire at `APPROVAL_TTL_SECONDS`.

2. `docs/ARCHITECTURE.md §12` — update G-7 status to
   `⚠️ Partially addressed — monitoring guidance added; auto-recovery requires spec patch`.

**Acceptance criteria:**

1. `approval_notify_failed` log events include `exc_info` (covered by PR-17).
2. `docs/N8N.md §8.3` documents the manual recovery procedure.
3. `docs/ARCHITECTURE.md §12` gap G-7 status updated.

**Definition of done:**

- All 3 acceptance criteria pass.
- No new application code in this PR.

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
