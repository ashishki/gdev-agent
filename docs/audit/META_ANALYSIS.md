---
# META_ANALYSIS — Cycle 5
_Date: 2026-03-08 · Type: targeted_

## Project State
Phase 4 (T13–T15) complete. Next: FIX-6 → FIX-7 (cross-tenant guard + SET LOCAL in rca_clusterer.py), then Phase 5 queue T16 → T17 → T18.
Baseline: 111 pass, 12 skip — unchanged from Cycle 4. No regressions.

Recent commits since Cycle 4 review:
- `feat(metrics)` — OTel tracing/metrics integration (may partially address ARCH-3)
- `feat(embedding)` — embedding service resize (may touch CODE-4 area)
- `refactor(docs)` — documentation updates

---

## Open Findings

| ID | Sev | Description | Files | Status |
|----|-----|-------------|-------|--------|
| FIX-6 | P1 | `assert` as cross-tenant guard — silently disabled under `-O`; complete raw_text PII leak | `app/jobs/rca_clusterer.py:400-411` | **CLOSED — Cycle 5 verified: `raise ValueError` present, no assert** |
| FIX-7 | P1 | 3 RCAClusterer session blocks missing `SET LOCAL` — job is silent no-op in production | `app/jobs/rca_clusterer.py:215,242,271,330` | **CLOSED — Cycle 5 verified: SET LOCAL in all 4 session contexts** |
| P1-1 | P1 | ADR-003 mandates RS256; HS256 implemented; no JWKS endpoint | `app/config.py:49`, `app/middleware/auth.py`, `docs/adr/003-rbac-design.md` | Open — architecture decision required |
| CODE-3 | P2 | Raw `tenant_id` UUID in log extra; must use `sha256[:16]` | `app/agent.py:578,602` | Open |
| CODE-4 | P2 | `Bearer ` literal fails mandatory secrets scan | `app/embedding_service.py:146` | Open |
| CODE-5 | P2 | Silent bare `except Exception` without LOGGER.warning in ANN fallback | `app/jobs/rca_clusterer.py:236` | Open |
| CODE-6 | P2 | No negative unit test for cross-tenant guard (depends on FIX-6) | `tests/test_rca_clusterer.py` | Open — fix after FIX-6 |
| CODE-7 | P2 | `summarize_cluster()` passes `tool_choice=auto` with `tools=[]` — invalid API combination | `app/llm_client.py:252-259` | Open |
| CODE-8 | P3 | `_fetch_embeddings` ANN fallback path has no unit test | `app/jobs/rca_clusterer.py`, `tests/test_rca_clusterer.py` | Open |
| ARCH-2 | P2 | ADR-002 stale: documents OpenAI/VECTOR(1536); actual Voyage AI/VECTOR(1024) | `docs/adr/002-vector-database.md` | Open — doc fix only |
| ARCH-3 | P2 | RCAClusterer missing OTel trace spans — ADR-004 violation | `app/jobs/rca_clusterer.py` | PARTIAL — Prometheus ✅ (`feat(metrics)` commit); OTel root trace spans still absent (observability.md §3.2) |
| ARCH-4 | P2 | RCA budget approximation bypasses CostLedger; costs not recorded per tenant | `app/jobs/rca_clusterer.py:164-180` | Open |
| ARCH-5 | P3 | RCA job timeout 300s vs ADR-005 example 120s; not documented | `app/jobs/rca_clusterer.py:120`, `docs/adr/005-orchestration-model.md` | Open |
| ARCH-6 | P2 | `GET /clusters/{id}` ticket_ids by timestamp heuristic, not membership | `app/routers/clusters.py:152-175` | Open |
| P2-1 | P2 | Redis keys not tenant-namespaced | `app/dedup.py`, `app/approval_store.py` | Deferred — Phase 5 |
| P2-6 | P2 | `agent.py:15` imports `HTTPException` from fastapi (layer violation) | `app/agent.py` | Deferred |
| P2-9 | P2 | `_run_blocking()` duplicated in agent.py and approval_store.py | `app/agent.py:495`, `app/approval_store.py` | Deferred |
| P2-10 | P2 | `get_settings()` at module level requires `ANTHROPIC_API_KEY` at import time | `app/main.py:179` | Open — documented |

---

## PROMPT_1 Scope (architecture)

- **OTel integration**: verify recent `feat(metrics)` commit satisfies ADR-004 §Instrumentation Scope for RCAClusterer (ARCH-3); confirm span hierarchy matches `docs/observability.md`
- **RCAClusterer budget path**: assess whether ARCH-4 (CostLedger bypass) is acceptable for Phase 5 or must be fixed; check if cluster cap approximation is documented in any ADR
- **ARCH-6 cluster membership**: evaluate whether timestamp heuristic is an acceptable interim contract or breaks API guarantees in spec.md
- **P1-1 carry-forward**: confirm Phase 5 (T16–T18) does not touch auth paths; if it does, RS256 decision must be made first

---

## PROMPT_2 Scope (code, priority order)

1. `app/jobs/rca_clusterer.py` (P1 fix targets FIX-6, FIX-7; also CODE-5, ARCH-3, ARCH-4)
2. `app/embedding_service.py` (CODE-4: `Bearer ` literal; verify if OTel commit touched this file)
3. `app/llm_client.py` (CODE-7: invalid tool_choice/tools combination in summarize_cluster)
4. `app/routers/clusters.py` (ARCH-6: ticket_ids heuristic)
5. `app/agent.py` (CODE-3: raw tenant_id in log; P2-6: fastapi import; P2-9: _run_blocking dup)
6. `tests/test_rca_clusterer.py` (CODE-6: missing negative test; CODE-8: ANN fallback path)
7. `docs/adr/002-vector-database.md` (ARCH-2: stale doc — Voyage AI/1024-dim)

---

## Cycle Type
Targeted — no new phase shipped; cycle covers FIX-6/FIX-7 fix verification plus review of OTel integration commit and carry-forward P2 findings before Phase 5 gate opens.

---

## Notes for PROMPT_3

- **Primary consolidation focus**: FIX-6 and FIX-7 must each have a concrete fix recommendation with exact line-level diff and test requirement. These are the hard gate for T16.
- **Secondary**: confirm ARCH-3 status after OTel commit — if already resolved, close it; if partial, describe what's missing.
- **Stop-ship condition**: if FIX-6 or FIX-7 are found unresolved (or partially resolved), PROMPT_3 must flag Stop-Ship: Yes for Phase 5.
- Archive Cycle 4 report to `docs/archive/PHASE4_REVIEW.md` as part of Cycle 5 consolidation (REVIEW_REPORT.md noted this requirement).
---
