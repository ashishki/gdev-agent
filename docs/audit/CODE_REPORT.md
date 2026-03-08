---
# CODE_REPORT — Cycle 4
_Date: 2026-03-08 · Reviewer: PROMPT_2_CODE (senior security engineer)_

---

## Checklist Summary

| Check | Result | Notes |
|-------|--------|-------|
| SEC-1 SQL parameterization | PASS | All new queries use named bind params; no f-string SQL |
| SEC-2 Tenant isolation | FAIL | `rca_clusterer.py` — 3 session blocks missing `SET LOCAL` |
| SEC-3 PII in logs | FAIL | `agent.py:578,602` — raw `tenant_id` UUID in log extra |
| SEC-4 Secrets scan | FAIL | `embedding_service.py:146` — `Bearer ` literal hits mandatory grep |
| SEC-5 Async correctness | PASS | All new async code uses `redis.asyncio`, `httpx.AsyncClient`, `asyncio.wait_for` |
| SEC-6 Auth/RBAC | PASS | Cluster endpoints enforce `require_role`; `require_role` returns `Depends(…)` confirmed |
| QUAL-1 Error handling | FAIL | `rca_clusterer.py:236` — bare `except Exception` with no log |
| QUAL-2 Observability | PARTIAL | EmbeddingService full; RCAClusterer: no OTel (carry-forward ARCH-3); clusters router: no metrics |
| QUAL-3 Test coverage | PARTIAL | Cross-tenant assertion, fallback query, Voyage error paths not tested |
| CF carry-forward | See below | P1-1, P2-6, P2-9, P2-10 open; no worsening |

---

## Findings

### CODE-1 [P1] — `assert` Used as Cross-Tenant Security Boundary in Production Code

Symptom: `_fetch_raw_texts_admin` uses Python `assert` to verify that admin-fetched rows belong to the requested tenant. Python optimizations (`-O` / `PYTHONOPTIMIZE=1`) silently disable all assertions.

Evidence: `app/jobs/rca_clusterer.py:382-383`
```python
cluster_tenant_id = str(row["tenant_id"])
assert cluster_tenant_id == tenant_id
```

Root cause: `assert` was used as a quick guard instead of an explicit conditional check. The `gdev_admin` session bypasses RLS; this assertion is the only cross-tenant safeguard after bypass.

Impact: If a container image is built or run with `-O` (common in some distroless/production Python configs), cross-tenant raw ticket text can be returned to the wrong tenant without any error or log. Complete cross-tenant PII leak for the raw_text field.

Fix: Replace with explicit check:
```python
if cluster_tenant_id != tenant_id:
    LOGGER.error("cross-tenant row detected", extra={...})
    raise ValueError(f"Cross-tenant isolation breach: got {cluster_tenant_id}, expected {tenant_id}")
```

Verify: Add negative unit test — admin stub returns row with mismatched `tenant_id`; call to `_upsert_cluster` must raise `ValueError` (not `AssertionError`). Confirm with `python -O -c "from app.jobs.rca_clusterer import ..."` that guard still fires.

Confidence: high

---

### CODE-2 [P1] — RCAClusterer `_db_session_factory` Sessions Missing `SET LOCAL app.current_tenant_id`

Symptom: `_fetch_embeddings`, `_deactivate_existing_clusters`, and the cluster write in `_upsert_cluster` open sessions from `_db_session_factory` without executing `SET LOCAL app.current_tenant_id`. In production, `ticket_embeddings` and `cluster_summaries` have RLS enabled and the `gdev_app` role has no `BYPASSRLS`. Queries run without `SET LOCAL` return zero rows or fail the `WITH CHECK` constraint.

Evidence:
- `app/jobs/rca_clusterer.py:212` — `_fetch_embeddings` session; no SET LOCAL before SELECT
- `app/jobs/rca_clusterer.py:258` — `_deactivate_existing_clusters` session; no SET LOCAL before UPDATE
- `app/jobs/rca_clusterer.py:314` — `_upsert_cluster` write session; no SET LOCAL before INSERT

Root cause: The background job uses `_db_session_factory` directly instead of going through `get_db_session`, which normally calls `SET LOCAL`. Dev-standards §3.6 requires `SET LOCAL` to precede all tenant-scoped queries.

Impact: The RCA clustering job is silently a no-op in production. `_fetch_embeddings` returns no rows (RLS blocks), `run_tenant` exits early at line 151, and no clusters are written. All unit tests use stub sessions that bypass this check.

Fix: Add `await session.execute(text("SET LOCAL app.current_tenant_id = :tid"), {"tid": tenant_id})` at the start of each session block in `_fetch_embeddings`, `_deactivate_existing_clusters`, and `_upsert_cluster`. Alternatively, switch these to `_admin_session_factory` if they are intended to run as `gdev_admin` (but then cross-tenant WHERE clauses must be verified extra carefully per CODE-1).

Verify: Integration test with real Postgres + RLS enabled policies: call `run_tenant(tenant_id)` and assert cluster rows are written to `cluster_summaries`.

Confidence: high

---

### CODE-3 [P2] — SEC-3: Raw `tenant_id` UUID in Application Log Fields

Symptom: Two log calls in `agent.py` include raw `tenant_id` UUID in `extra` dict, violating dev-standards §3.5 which mandates `sha256(str(tenant_id))[:16]` for all tenant identifiers in logs.

Evidence:
- `app/agent.py:578` — `"context": {"tenant_id": str(tenant_uuid)}` in `_record_cost_best_effort`
- `app/agent.py:602` — `"context": {"tenant_id": tenant_id, "ticket_id": ticket_id}` in `_schedule_embedding`

Root cause: Log lines added during T13 integration of `_schedule_embedding` without applying the standard hash pattern used in all other agent methods.

Impact: Tenant UUIDs are emitted to application logs, which flow into Grafana Loki / CloudWatch / any log aggregation pipeline. Violates the PII minimization model documented in `data-map.md §5` (tenant_id = Low PII, but still must be hashed per dev-standards to prevent cross-referencing).

Fix: Use `_sha256_short = lambda v: hashlib.sha256(v.encode()).hexdigest()[:16]` (already defined in `embedding_service.py` and `rca_clusterer.py`). Replace `"tenant_id": str(tenant_uuid)` with `"tenant_id_hash": _sha256_short(str(tenant_uuid))` in both locations.

Verify: `git grep -n '"tenant_id":' app/agent.py` must return zero matches.

Confidence: high

---

### CODE-4 [P2] — SEC-4: `Bearer ` Literal Triggers Mandatory Secrets Scan

Symptom: `git grep -rn "Bearer " app/` returns one hit in `embedding_service.py`. Dev-standards §8 requires this grep to be empty before any task is declared done. Current output:
```
app/embedding_service.py:146:        headers = {"Authorization": f"Bearer {self._settings.voyage_api_key}"}
```

Evidence: `app/embedding_service.py:146`

Root cause: The Voyage AI request constructs an `Authorization` header inline using an f-string with the literal `Bearer `. Not a hardcoded secret (key comes from `settings.voyage_api_key`) but the string pattern matches the scan pattern.

Impact: Every CI run of the pre-commit secrets scan blocks on this file. If the scan gate is enforced, T13 cannot be merged until this is resolved.

Fix: Either (a) move the auth header construction to avoid the literal, e.g. `{"Authorization": "Bearer " + self._settings.voyage_api_key}` does NOT help (same literal). Better: use a named constant `_BEARER_PREFIX = "Bearer "` defined outside functions, or use an httpx `Auth` subclass. (b) Explicitly document as a false positive with `# noqa: secrets-scan — runtime secret from settings, not hardcoded` and update the scan pattern to exclude this pattern. Option (a) is cleaner.

Verify: `git grep -rn "Bearer " app/` returns empty.

Confidence: high

---

### CODE-5 [P2] — QUAL-1: Silent `except Exception` Without Log in `_fetch_embeddings`

Symptom: The ANN-ordered query in `_fetch_embeddings` wraps the primary `session.execute` in an `except Exception` that silently falls through to a fallback query with no logging.

Evidence: `app/jobs/rca_clusterer.py:236-254`
```python
except Exception:
    rows = (
        (
            await session.execute(
                text("""SELECT ... ORDER BY created_at DESC LIMIT 500"""),
                ...
            )
        )
        ...
    )
```

Root cause: Dev-standards §3.4 mandates `LOGGER.warning(..., exc_info=True)` on all `except Exception` blocks. This block was omitted.

Impact: pgvector index failures, missing extension errors, or operator support errors (ANN distance operator requires pgvector index) are invisible in logs. Operators have no signal that the fallback path is active. If the fallback itself fails, that exception propagates unmasked through `_fetch_embeddings`, reaching `run_tenant`'s bare `finally` block.

Fix: Add before the fallback query:
```python
LOGGER.warning(
    "rca ann query failed, falling back to date order",
    extra={"event": "rca_ann_fallback", "context": {"tenant_id_hash": _sha256_short(tenant_id)}},
    exc_info=True,
)
```

Verify: Test that triggers the except branch shows structured log output.

Confidence: high

---

### CODE-6 [P2] — QUAL-3: Cross-Tenant Isolation Assertion Has No Negative Test

Symptom: `_fetch_raw_texts_admin` performs a cross-tenant guard (`assert cluster_tenant_id == tenant_id`) but there is no unit test that verifies the guard fires when admin returns a wrong-tenant row.

Evidence: `app/jobs/rca_clusterer.py:382-383`; `tests/test_rca_clusterer.py` — no test with mismatched tenant_id from admin session.

Root cause: Test coverage gap. Combined with CODE-1, the `assert` will be silently skipped under optimization, and no test catches it.

Impact: Regression risk: if the cross-tenant check is accidentally removed or changed, no test fails. This is the most security-critical isolation boundary in the new code.

Fix: After CODE-1 fix (explicit ValueError), add test:
```python
async def test_fetch_raw_texts_admin_raises_on_cross_tenant_row():
    admin_stub = _SessionStub(rows=[{"tenant_id": "other-tenant", "raw_text": "leaked text"}])
    clusterer = RCAClusterer(..., admin_session_factory=_SessionFactoryStub(admin_stub))
    with pytest.raises(ValueError, match="Cross-tenant"):
        await clusterer._fetch_raw_texts_admin(tenant_id="tenant-1", ticket_ids=[str(uuid4())])
```

Verify: Test passes after CODE-1 fix; fails before it.

Confidence: high

---

### CODE-7 [P2] — `summarize_cluster` Sends `tool_choice=auto` With Empty Tools List

Symptom: `llm_client.summarize_cluster()` passes `tools=[]` and `tool_choice={"type": "auto"}` to the Anthropic API. The `tool_choice` parameter is only valid when `tools` is non-empty. The API may return a validation error (400) for this combination.

Evidence: `app/llm_client.py:252-259`
```python
response = self._create_message(
    model=self.settings.anthropic_model,
    max_tokens=250,
    system="You summarize ticket clusters ...",
    tools=[],
    tool_choice={"type": "auto"},   # <-- invalid when tools=[]
    messages=[{"role": "user", "content": prompt}],
)
```

Root cause: `tool_choice` was copied from the main `run_agent` invocation and not removed for the single-call summarize path.

Impact: If Anthropic API rejects the call, `_create_message` raises an `APIStatusError`. The caller `_upsert_cluster` catches `except Exception` and falls back to `label = f"Cluster {cluster_number}"`. Every cluster in every run would silently use the generic label, with no useful RCA summary. The failure is masked by the broad exception handler (see CODE-5 pattern).

Fix: Remove `tool_choice` from the `summarize_cluster` call, or set `tool_choice={"type": "none"}` when `tools=[]`.

Verify: Unit test mocks `_create_message` and asserts no `tool_choice` key is present in kwargs when called from `summarize_cluster`.

Confidence: medium (Anthropic API behavior with `tools=[]` + `tool_choice` not fully specified in public docs; may silently ignore `tool_choice`)

---

### CODE-8 [P3] — QUAL-3: `_fetch_embeddings` Fallback Query Path Not Covered

Symptom: Lines 238–254 (ANN fallback path in `_fetch_embeddings`) are not exercised by any test. `_fetch_embeddings` is monkeypatched in the existing cap test, so no test lets the real code path run.

Evidence: `tests/test_rca_clusterer.py` — no test makes `session.execute` raise on first call and succeed on second.

Root cause: Coverage gap; exception injection not tested.

Impact: If fallback SQL contains a bug (e.g., wrong column name after schema change), it is undetected until production.

Fix: Add test using a session stub that raises on the first `execute` call (ANN query) and returns rows on the second (fallback):
```python
async def test_fetch_embeddings_falls_back_on_ann_failure():
    ...
```

Verify: Coverage shows lines 238–254 covered.

Confidence: high

---

## Carry-Forward Findings

| ID | Sev | Status | Evidence |
|----|-----|--------|----------|
| P1-1 | P1 | Open — unchanged | `app/config.py:49` — `jwt_algorithm: str = "HS256"`; ADR-003 mandates RS256 |
| P2-6 | P2 | Open — unchanged | `app/agent.py:15` — `from fastapi import HTTPException`; layer violation |
| P2-9 | P2 | Open — unchanged | `_run_blocking` still duplicated in `app/agent.py:495` and `app/approval_store.py` |
| P2-10 | P2 | Open — unchanged | `app/main.py:179` — `_middleware_settings = get_settings()` at module level |

No carry-forward finding has worsened this cycle.

---

## Finding Index

| ID | Sev | Title |
|----|-----|-------|
| CODE-1 | P1 | `assert` used as cross-tenant security boundary |
| CODE-2 | P1 | RCAClusterer sessions missing `SET LOCAL` — job silently no-op in production |
| CODE-3 | P2 | Raw `tenant_id` UUID in log fields (`agent.py:578,602`) |
| CODE-4 | P2 | `Bearer ` literal fails mandatory secrets scan |
| CODE-5 | P2 | Silent bare `except Exception` in `_fetch_embeddings` |
| CODE-6 | P2 | Cross-tenant assertion has no negative test |
| CODE-7 | P2 | `summarize_cluster` sends `tool_choice=auto` with empty tools list |
| CODE-8 | P3 | `_fetch_embeddings` fallback path not unit-tested |

---

CODE review done. P0: 0, P1: 2, P2: 5, P3: 1. Run PROMPT_3_CONSOLIDATED.md.
