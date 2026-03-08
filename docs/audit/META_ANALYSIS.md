---
# META_ANALYSIS — Cycle 7
_Date: 2026-03-08 · Type: targeted_

## Project State
Phase 4 (T13–T15) is complete and Phase 5 is in progress; next: T16 — OpenTelemetry Trace Instrumentation (then T17 → T18).
Baseline: 111 pass, 12 skip, 0 fail — unchanged vs Cycle 6.

## Open Findings
| ID | Sev | Description | Files | Status |
|----|-----|-------------|-------|--------|
| ARCH-1 | P1 | ADR-003 requires RS256 + JWKS, but runtime is HS256 and no JWKS endpoint exists | `app/config.py`, `app/middleware/auth.py`, `app/routers/auth.py`, `docs/adr/003-rbac-design.md` | Open (auth-phase gate) |
| CODE-5 | P2 | ANN fallback keeps broad exception path without required warning/trace context | `app/jobs/rca_clusterer.py` | Open |
| CODE-9 | P2 | Async RCA flow calls sync `summarize_cluster()`, risking event-loop blocking | `app/jobs/rca_clusterer.py`, `app/llm_client.py` | Open |
| CODE-10 | P2 | `/metrics` route lacks explicit RBAC/exemption contract alignment | `app/main.py` | Open |
| ARCH-2 | P2 | ADR-002 vector stack drift (docs say OpenAI/1536, runtime uses Voyage/1024) | `docs/adr/002-vector-database.md`, `app/config.py` | Open |
| ARCH-3 | P2 | RCA observability remains partial; background OTel span hierarchy incomplete | `app/jobs/rca_clusterer.py`, `docs/observability.md` | Partial |
| ARCH-4 | P2 | RCA cost path bypasses tenant CostLedger accounting | `app/jobs/rca_clusterer.py` | Open |
| ARCH-6 | P2 | Cluster details endpoint uses time-window heuristic instead of persisted membership | `app/routers/clusters.py` | Open |
| ARCH-7 | P2 | Service-layer boundary violation (`HTTPException` import in service module) | `app/agent.py` | Open |
| P2-1 | P2 | Redis keys in hot paths are not tenant-namespaced | `app/dedup.py`, `app/approval_store.py`, `app/middleware/rate_limit.py` | Open (deferred) |
| P2-9 | P2 | `_run_blocking()` helper duplicated across modules | `app/agent.py`, `app/approval_store.py` | Open (deferred) |
| P2-10 | P2 | Module-level settings path can require API key at import time | `app/main.py`, `tests/conftest.py` | Open |
| CODE-8 | P3 | ANN fallback exception path still lacks direct unit coverage | `app/jobs/rca_clusterer.py`, `tests/test_rca_clusterer.py` | Open |
| ARCH-5 | P3 | RCA timeout (300s) diverges from ADR-005 example (120s) without explicit rationale | `app/jobs/rca_clusterer.py`, `docs/adr/005-orchestration-model.md` | Open |

## PROMPT_1 Scope (architecture)
- Auth architecture decision path: resolve ADR-003 contract (RS256+JWKS vs HS256 amendment) and define required runtime/doc/test alignment.
- Observability architecture completeness for Phase 5: verify trace topology for RCA background flows and `/metrics` exposure policy contract.
- RCA contract integrity: reconcile CostLedger integration, timeout rationale, and cluster membership semantics with ADR/spec docs.
- Architecture drift cleanup set: ADR-002 vector model mismatch and service-boundary contract (ARCH-7).

## PROMPT_2 Scope (code, priority order)
1. `app/jobs/rca_clusterer.py` (changed + highest finding density: CODE-5/CODE-8/CODE-9/ARCH-3/ARCH-4/ARCH-5)
2. `app/main.py` (changed; CODE-10 and settings-init path P2-10)
3. `app/llm_client.py` (changed dependency for CODE-9)
4. `app/middleware/auth.py` (security-critical; ARCH-1 validation)
5. `app/routers/auth.py` (security-critical; JWKS/algorithm contract)
6. `app/config.py` (security/architecture-critical config drift: ARCH-1, ARCH-2)
7. `app/routers/clusters.py` (regression/contract check: ARCH-6)
8. `app/agent.py` (service-boundary + helper duplication checks: ARCH-7, P2-9)
9. `app/dedup.py` (tenant key namespace check: P2-1)
10. `app/approval_store.py` (tenant key namespace + helper duplication: P2-1, P2-9)
11. `app/middleware/rate_limit.py` (security-critical tenant namespace check: P2-1)
12. `tests/conftest.py` and `tests/test_rca_clusterer.py` (import-time config and fallback-path coverage checks)

## Cycle Type
Targeted — no new phase boundary closed; this cycle focuses on carry-forward P1/P2 findings and Phase 5 observability/auth contract drift.

## Notes for PROMPT_3
Prioritize consolidation on: (1) explicit decision/status for ARCH-1, (2) whether CODE-9 and CODE-10 create operational risk for Phase 5 rollout, and (3) which open items remain blockers vs deferred debt before starting Phase 6 auth hardening work.
---
