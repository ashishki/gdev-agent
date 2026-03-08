---
# META_ANALYSIS — Cycle 4
_Date: 2026-03-08 · Type: full_

## Project State

Phase 4 (T13–T15) complete. Next: STOP — user runs Cycle 4 review before T16.
Baseline: 111 pass, 12 skip (unchanged from Cycle 3; integration tests skip without Docker/TEST_DATABASE_URL).

## Open Findings

| ID | Sev | Description | Files | Status |
|----|-----|-------------|-------|--------|
| P1-1 | P1 | ADR-003 mandates RS256; HS256 implemented — no key rotation without redeploy, no JWKS | `app/config.py:45-46`, `app/middleware/auth.py`, `app/routers/auth.py`, `docs/adr/003-rbac-design.md` | Open — architecture decision required |
| P2-1 | P2 | Redis keys not tenant-namespaced (doc vs code drift) | `docs/data-map.md §3`, `app/dedup.py`, `app/approval_store.py` | Open — deferred to Phase 5 |
| P2-6 | P2 | `agent.py` imports `HTTPException` from fastapi (layer violation) | `app/agent.py` | Open — deferred |
| P2-9 | P2 | `_run_blocking()` duplicated in `store.py` and `agent.py` | `app/approval_store.py`, `app/agent.py` | Open — deferred |
| P2-10 | P2 | `get_settings()` requires `ANTHROPIC_API_KEY` at import time; workaround in conftest | `app/main.py`, `tests/conftest.py` | Open — documented |

## PROMPT_1 Scope (architecture)

- **EmbeddingService** (`app/embedding_service.py`): new component — Voyage AI voyage-3-lite integration, SHA-256 mock in dev/test, fire-and-forget asyncio.create_task() pattern, VECTOR(1024) upsert. Verify isolation: failure must not affect /webhook response path.
- **RCA Clusterer** (`app/jobs/rca_clusterer.py`): new background job — APScheduler every 15 min, pgvector ANN + DBSCAN(eps=0.15, min_samples=3), gdev_admin role for raw_text fetch, asyncio.wait_for timeout=300. Security-critical: admin role bypass must include WHERE tenant_id=$1 and cluster_tenant_id assertion.
- **Cluster API** (`app/routers/clusters.py`): new router — GET /clusters, GET /clusters/{id}. Security-critical: RLS scope, viewer+ role, cross-tenant 404, no cost/audit data to viewer.
- **Migration 0004** (`alembic/versions/0004_resize_ticket_embeddings_vector_to_1024.py`): vector column resize — verify upgrade/downgrade correctness, conditional pgvector check retained.
- **Modified core** (`app/agent.py`, `app/config.py`, `app/llm_client.py`, `app/main.py`, `app/schemas.py`): verify T13/T14 integration hooks don't introduce regressions in existing agent pipeline.

## PROMPT_2 Scope (code, priority order)

1. `app/jobs/rca_clusterer.py` (new — admin role, cross-tenant assertion, timeout, budget check)
2. `app/embedding_service.py` (new — fire-and-forget isolation, mock correctness, upsert SQL)
3. `app/routers/clusters.py` (new — auth, RLS, cross-tenant 404, viewer data exposure)
4. `alembic/versions/0004_resize_ticket_embeddings_vector_to_1024.py` (new migration — upgrade/downgrade)
5. `app/agent.py` (changed — T13 hook, open P2-6 carry-forward)
6. `app/config.py` (changed — new config fields: embedding_model, rca_lookback_hours, rca_budget_per_run_usd; open P1-1 carry-forward)
7. `app/llm_client.py` (changed — summarize_cluster() single-call path, no tool_use loop)
8. `app/main.py` (changed — APScheduler registration, open P2-10 carry-forward)
9. `app/schemas.py` (changed — new cluster/embedding schemas)
10. `tests/test_embedding_service.py` (new — coverage of mock path and upsert)
11. `tests/test_rca_clusterer.py` (new — cross-tenant assertion, timeout, cluster label fallback)
12. `tests/test_endpoints.py` (changed — regression check on /clusters endpoints)
13. `tests/test_main.py` (changed — regression check for APScheduler registration)

## Cycle Type

Full — Phase 4 (T13–T15) implemented in full. All three tasks have new files on disk. Baseline unchanged. Review gate required before T16.

## Notes for PROMPT_3

- **Priority consolidation focus**: gdev_admin role misuse in rca_clusterer (WHERE tenant_id check + pre-LLM assertion), fire-and-forget exception isolation in EmbeddingService, viewer data exposure in cluster endpoints.
- Carry P1-1 (RS256 decision) forward; escalate if Phase 5 touches auth.
- Verify baseline is still 111 pass / 12 skip after Phase 4 changes — if delta, investigate before closing cycle.
- Check that `app/jobs/` uses only `redis.asyncio` (no sync Redis in async context per P2-pattern).
---
