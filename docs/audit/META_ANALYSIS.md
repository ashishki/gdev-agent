---
# META_ANALYSIS — Cycle 6
_Date: 2026-03-08 · Type: targeted_

## Project State
Phase 4 (T13–T15) is complete and Phase 5 is in progress; next actionable queue remains T16 → T17 → T18, then run the Phase 5 gate audit.
Baseline: 111 pass, 12 skip — unchanged vs previous cycle.

## Open Findings
| ID | Sev | Description | Files | Status |
|----|-----|-------------|-------|--------|
| ARCH-1 | P1 | ADR-003 mandates RS256; implementation still HS256, no JWKS endpoint | `app/config.py`, `app/middleware/auth.py`, `docs/adr/003-rbac-design.md` | Open — architecture decision required before auth-phase work |
| CODE-3 | P2 | Raw `tenant_id` UUID appears in logs; must hash (`sha256[:16]`) | `app/agent.py` | Open |
| CODE-4 | P2 | `Bearer ` literal fails mandatory secrets scan rule | `app/embedding_service.py` | Open |
| CODE-5 | P2 | ANN fallback has broad `except Exception` path without required warning+trace context | `app/jobs/rca_clusterer.py` | Open |
| CODE-6 | P2 | Missing negative unit test for cross-tenant guard (FIX-6 behavior) | `tests/test_rca_clusterer.py` | Open (unblocked) |
| CODE-7 | P2 | `tool_choice=auto` with `tools=[]` can produce invalid LLM API request | `app/llm_client.py` | Open |
| ARCH-2 | P2 | ADR-002 stale (OpenAI/1536) vs implemented Voyage/1024 | `docs/adr/002-vector-database.md` | Open (doc drift) |
| ARCH-3 | P2 | RCA observability is partial: Prometheus present, OTel root span hierarchy still incomplete | `app/jobs/rca_clusterer.py`, `tests/test_observability.py` | Partial |
| ARCH-4 | P2 | RCA costs bypass CostLedger accounting per tenant | `app/jobs/rca_clusterer.py` | Open (deferred) |
| ARCH-6 | P2 | `GET /clusters/{id}` ticket list uses timestamp heuristic, not true membership | `app/routers/clusters.py` | Open (pre-GA fix required) |
| P2-1 | P2 | Redis keys not tenant-namespaced | `app/dedup.py`, `app/approval_store.py` | Open (deferred) |
| P2-6 | P2 | Service-layer import boundary violation (`HTTPException` in agent module) | `app/agent.py` | Open (deferred) |
| P2-9 | P2 | `_run_blocking()` duplicated across modules | `app/agent.py`, `app/approval_store.py` | Open (deferred) |
| P2-10 | P2 | Module-level `get_settings()` path requires API key at import time | `app/main.py`, `tests/conftest.py` | Open |
| CODE-8 | P3 | ANN fallback branch lacks direct exception-path unit coverage | `app/jobs/rca_clusterer.py`, `tests/test_rca_clusterer.py` | Open |
| ARCH-5 | P3 | RCA timeout (300s) diverges from ADR example (120s) without explicit ADR clarification | `app/jobs/rca_clusterer.py`, `docs/adr/005-orchestration-model.md` | Open |

## PROMPT_1 Scope (architecture)
- Observability architecture delta from latest commit (`refactor(metrics/middleware)`): validate trace topology and metric contract alignment with `docs/observability.md` for T16/T17.
- Middleware contract drift review for auth/signature/rate-limit touched in latest commit: verify tenant/security invariants stayed intact after refactor.
- Re-check carry-forward architectural risks impacted by changed files: ARCH-1 (auth path touched), ARCH-3 (OTel completeness), ARCH-4 (CostLedger), ARCH-6 (cluster membership contract).

## PROMPT_2 Scope (code, priority order)
1. `app/metrics.py` (new)
2. `tests/test_metrics.py` (new/changed verification)
3. `tests/test_observability.py` (changed verification)
4. `app/main.py` (changed; metrics endpoint + startup wiring)
5. `app/agent.py` (changed; CODE-3/P2-6/P2-9 regression check)
6. `app/jobs/rca_clusterer.py` (changed; CODE-5/CODE-6/CODE-8 + ARCH-3/ARCH-4)
7. `app/embedding_service.py` (changed; CODE-4)
8. `app/middleware/auth.py` (security-critical changed)
9. `app/middleware/signature.py` (security-critical changed)
10. `app/middleware/rate_limit.py` (security-critical changed)
11. `app/llm_client.py` (carry-forward CODE-7)
12. `app/routers/clusters.py` (carry-forward ARCH-6)

## Cycle Type
Targeted — no phase boundary has completed yet (T16–T18 still in progress), but there is a substantial unaudited code delta in observability + middleware paths and carry-forward P1/P2 findings to verify.

## Notes for PROMPT_3
Prioritize consolidation on: (1) whether auth/middleware refactor introduced any tenant-isolation or auth regressions, (2) whether T16/T17 acceptance criteria are actually met, and (3) whether ARCH-1 remains isolated from Phase 5 work or became a direct blocker due to auth-file edits.
---
