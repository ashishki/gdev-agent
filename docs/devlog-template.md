# Dev Log Template

_Copy this file to `docs/devlog/{YYYY-MM-DD}-{short-slug}.md` for each significant incident,
bug fix, or architectural change. Do not edit this template — add entries as new files._

---

## How to Use

Create a new file for each of these events:
- A production bug or regression.
- An architectural decision that deviates from a current ADR.
- A prompt change that required a rollback.
- A performance incident or SLA breach.
- A security finding (guard bypass, PII exposure, auth failure).
- A major refactor that changes file structure or module contracts.

Minor changes tracked in git history only; no devlog entry needed.

---

```
# {date} — {short title}

**Type:** bug | security | performance | architecture | prompt | regression | incident
**Severity:** critical | high | medium | low
**Affected component(s):** {e.g., LLMClient, OutputGuard, RCAClusterer, ApprovalStore}
**Affected tenants:** all | {tenant_slug} | none (dev only)
**Discovered by:** {who found it: monitoring alert | eval run | manual test | user report}
**Reporter:** {name or "automated"}

---

## What Failed

{Factual description of the symptom. What was observed? What was the user/system impact?
Be specific: include error messages, metric values, request IDs, time range.}

Example:
> At 14:32 UTC on 2026-03-03, `gdev_guard_blocks_total{guard_type="output"}` spiked to
> 42 blocks in 5 minutes for tenant `acme-games`. No player-facing replies were sent during
> this window. Alert fired; on-call notified.

---

## Why It Failed

{Root cause analysis. Do not stop at the proximate cause — identify the underlying reason.
Use the 5-Whys or similar. Was this a code bug, a configuration error, an external API
change, a data issue, or an architecture gap?}

Example:
> The Anthropic API silently changed its tool_call response format for multi-turn conversations
> in a minor update. The `LLMClient` expected `tool_use.input` to be a dict, but the API
> began returning it as a JSON-encoded string. `json.loads()` was not applied, causing Pydantic
> validation to fail. The output guard then blocked the malformed draft.
>
> Root cause: No contract test for the Anthropic API response schema. We relied on informal
> assumptions, not an explicit validation layer.

---

## How It Was Fixed

{Concrete description of the fix. Reference the PR, commit hash, or file change.
Include the specific lines changed if relevant.}

Example:
> PR #47: `app/llm_client.py` — added `json.loads()` call on `tool_use.input` when it is
> a string. Added unit test `test_llm_client.py::test_tool_input_string_coercion` to cover
> this case. Deployed at 15:10 UTC; guard block rate returned to 0 within 2 minutes.

---

## What Changed in Architecture or Documentation

{Did this fix require an ADR update? A spec change? A data-map change? A new guardrail?
If yes, list the documents updated and summarize the change.}

Example:
> - `docs/agent-registry.md` §1 (TriageAgent / Failure Modes): added row for
>   `"LLM response schema change"` with behavior `"json.loads() coercion applied; test in CI"`.
> - `docs/adr/006-anthropic-contract-tests.md`: new ADR drafted to formalize API response
>   schema testing as a CI requirement.
> - No spec.md change required (this was an implementation gap, not a scope change).

---

## What Was Learned

{Honest retrospective. What should be done differently in the future? What assumption was
wrong? What monitoring or test was missing?}

Example:
> 1. External API responses must be validated, not assumed. Any API whose schema can change
>    without a version bump needs a contract test.
> 2. The alert fired correctly, but the runbook didn't exist yet. Added runbook
>    `docs/runbooks/output-guard-spike.md`.
> 3. The 5-minute silence from the approval channel (Telegram) was a secondary symptom that
>    went unnoticed; add an alert for `approval_notification_failures > 0`.

---

## Follow-up Actions

| Action | Owner | Target date | Status |
|---|---|---|---|
| Add contract test for Anthropic tool_use schema | {name} | {date} | open |
| Write runbook for output-guard-spike alert | {name} | {date} | open |
| Add approval notification failure alert | {name} | {date} | open |

---

**Closed:** {date when all follow-up actions completed, or "open"}
```

---

## Example Entries

### Example 1 — Bug

`docs/devlog/2026-03-05-approval-store-double-execute.md`

> **Type:** bug · **Severity:** high
> **What failed:** Approval actions were executing twice in a race condition when two
> support agents clicked approve simultaneously.
> **Why:** `pop_pending()` called `GETDEL` then redundantly called `DELETE` on the same key.
> The double-delete was harmless, but the root issue was that `GETDEL` atomicity was not
> relied upon correctly in the execute path.
> **Fix:** Removed the redundant `self.redis.delete(key)` call after `GETDEL`. Added
> integration test for concurrent approval attempts.

### Example 2 — Architecture

`docs/devlog/2026-03-10-migrate-sqlite-to-postgres.md`

> **Type:** architecture · **Severity:** low (planned migration)
> **What changed:** Replaced `EventStore` (SQLite) with Postgres `PGEventStore`.
> Removed `sqlite_log_path` config. Updated `docs/data-map.md` §1 (SQLite row deleted).
> Updated `docker-compose.yml` (removed SQLite volume).

### Example 3 — Performance

`docs/devlog/2026-03-15-rca-slow-query.md`

> **Type:** performance · **Severity:** medium
> **What failed:** RCA Clusterer for tenant `megacorp` took 7 minutes (SLA: 5 min).
> **Why:** `ticket_embeddings` table had 800K rows (2 years × high-volume tenant).
> HNSW index was created with default `m=16`; ANN query scanned too many candidates.
> **Fix:** Rebuilt HNSW index with `ef_construction=128`. Query time dropped to 800 ms.
> Updated `docs/data-map.md` §2 with index creation notes.
