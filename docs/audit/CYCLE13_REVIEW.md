---
# REVIEW_REPORT — Cycle 13
_Date: 2026-03-21 · Scope: Phase 12 (FIX-I + SVC-4) · Baseline before: 214 pass, 0 fail · Baseline after: 215 pass, 0 fail_

## Executive Summary

- Stop-Ship: **No** — repo is green; 215 pass / 0 fail. All Phase 12 acceptance criteria confirmed.
- Phase 12 complete: FIX-I (batch-close 9 Cycle 12 P2 findings) + SVC-4 (WebhookService/ApprovalService extraction).
- Two P1 findings identified and resolved within this cycle (see below).
- No new P0 findings. No carry-forward P1 findings.
- All Cycle 12 open findings (CODE-4..15, ARCH-5, ARCH-9, ARCH-11) confirmed closed.

---

## P0 Issues

_None this cycle._

---

## P1 Issues

### P1-C13-1 · Inconsistent AgentError handling in /webhook and /approve handlers

**File:** `app/main.py:308-334`
**Reviewer:** CODE
**Status:** FIXED in Cycle 13

**Finding:** After SVC-4, /webhook caught base `AgentError` and re-wrapped it as `HTTPException`,
while re-raising subclasses directly. /approve wrapped all `AgentError` as `HTTPException`.
This was asymmetric and redundant — the custom `@app.exception_handler(AgentError)` already
handles all AgentError instances at the ASGI level.

**Fix:** Removed `try/except AgentError` blocks from both handlers entirely. Both handlers now
let `AgentError` propagate to the registered custom exception handler. Removed unused
`HTTPException` import from `app/main.py`. Tests in `test_main.py` (which call handlers
directly, not via ASGI stack) updated to expect `AgentError` rather than `HTTPException`.

**Verification:** 215 tests pass, ruff clean.

---

### P1-C13-2 · Missing test for request-tenant fallback path in WebhookService

**File:** `tests/test_webhook_service.py`
**Reviewer:** CODE
**Status:** FIXED in Cycle 13

**Finding:** WebhookService.handle() resolves tenant_id as:
`resolved_tenant_id = request_tenant_id or payload.tenant_id`
No test covered the path where `request.state.tenant_id` is set but `payload.tenant_id` is None.
This is the production path when JWT middleware provides tenant context.

**Fix:** Added `test_handle_uses_request_tenant_when_payload_has_none` to verify that
request-state tenant_id is used when payload omits it.

---

## P2 Issues

### P2-C13-1 · ARCHITECTURE.md missing WebhookService/ApprovalService entries

**File:** `docs/ARCHITECTURE.md`
**Reviewer:** ARCH
**Status:** FIXED in Cycle 13 (doc update pass)

**Finding:** Section 2.1 component table and repository layout did not include
`webhook_service.py` or `approval_service.py`.

**Fix:** ARCHITECTURE.md updated with new service entries and file layout.

---

## P3 Issues (informational, no action required this cycle)

- **P3-C13-1:** `_NoopSpan`/`_NoopTracer` duplicated across 6 modules (~80 lines). Consider
  extracting to `app/tracing.py` in a future cleanup pass.
- **P3-C13-2:** Test for `approve_secret=None` (allow-all) path not present in
  `test_approval_service.py`. Behavior is correct in code; test gap is low risk.
- **P3-C13-3:** Dedup cache in WebhookService catches all `Exception` without semantic
  distinction between validation and infrastructure errors.

---

## META Analysis

**Process health: WARN (informational)**

- Test baseline is now correctly stated as "215 pass + 0 skip (integration tests run with
  `TEST_DATABASE_URL` pointing to local PG 5433)". Prior phrasing "198 pass / 14 skip
  (Docker-required)" was a legacy note from before the local PG setup was established.
- All Cycle 12 P2 closures verified by code inspection — no phantom closures detected.
- Recommendation for future cycles: extract P3 carry-forwards (tracer noop duplication) in a
  dedicated cleanup sprint rather than accumulating across review cycles.

---

## Metrics

| Metric | Before | After |
|--------|--------|-------|
| Tests passing | 214 | 215 |
| P0 findings | 0 | 0 |
| P1 findings | 0 → 2 | 2 (fixed) |
| P2 findings | 0 → 1 | 1 (fixed) |
| P3 findings | 0 → 3 | 3 (deferred) |
| Open findings | 0 | 0 |

**All Phase 12 deliverables confirmed complete. Platform is in "Done" state per tasks.md Success Metrics.**
