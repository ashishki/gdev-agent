# META_ANALYSIS — Cycle 17
_Date: 2026-06-14 · Type: full_

## Project State
Phase 5 (T18–T20) complete. Next: T21 — Compose Migration And Health Hardening.
Baseline: orchestrator-verified `.venv/bin/python -m pytest tests/ -q` -> 272 passed, 0 skipped, 45 warnings. Changed from Cycle 16 baseline: +9 passed, skip count unchanged, +3 warnings.

## Open Findings
| ID | Sev | Description | Files | Status |
|----|-----|-------------|-------|--------|
| ARCH-HARDEN-1 | P2 | `docs/ARCHITECTURE.md` eval summary still references the old 25-case/basic metric shape after T07–T10. | `docs/ARCHITECTURE.md` | Open — carried forward in CODEX_PROMPT; should be folded into the Phase 6 architecture refresh. |
| ARCH-1 | P2 | Ticket, analytics, and cluster read APIs still embed query, pagination, metrics, and response assembly logic in route handlers. | `app/routers/tickets.py`, `app/routers/analytics.py`, `app/routers/clusters.py` | Open — service extraction drift; non-blocking for T21 but should remain visible. |
| ARCH-2 | P2 | Main architecture spec describes an older system snapshot, including stale audit/eval/load/observability evidence. | `docs/ARCHITECTURE.md` | Open — CODEX_PROMPT carries this as required cleanup before final packaging. |
| CODE-3 / ARCH-3 | P3 | `docs/load-profile.md` mixes target assumptions with unmeasured local/synthetic load evidence. | `docs/load-profile.md` | Open — non-blocking; clarify measured vs target claims during Phase 6 evidence packaging. |
| CODE-1 | P2 | Data map previously documented tenant RLS context as connection-level setup instead of transaction-local `SET LOCAL`. | `docs/data-map.md` | Resolved/regression-check — current data map documents `set_config(..., true)` inside `session.begin()` as transaction-local; verify in PROMPT_2 because it is security-critical. |
| CODE-2 | P2 | README previously overstated service-layer separation while read routes still contain query/pagination/response logic. | `README.md` | Resolved/regression-check — README now limits service-layer separation to main write/auth/eval workflows and names read-route extraction as remaining architecture drift. |

## PROMPT_1 Scope (architecture)
- tenant isolation proof: review Phase 5's canonical security boundary across `docs/TENANT_ISOLATION.md`, `docs/data-map.md`, README, evidence index, failure modes, RLS migrations, JWT/RBAC, webhook signatures, approvals, secrets, and cost ledger separation.
- adversarial tenant scenarios: review whether T20's audit-read, approval, missing/invalid tenant slug, and invalid-HMAC examples match the documented threat boundaries without claiming external production controls.
- Phase 6 readiness shape: review T21/T22 architecture for compose migration checks, health/readiness/liveness behavior, secrets, backup/restore notes, production-like config language, and explicit non-production-readiness boundaries.
- targeted architecture refresh: include `docs/ARCHITECTURE.md` updates for current eval/evidence wording, compose/health/deployment-readiness positioning, and stale system snapshot drift before final packaging.
- carry-forward layer boundary drift: keep read-route service extraction visible as architecture debt unless T21/T22 intentionally expands scope, which is not currently required.

## PROMPT_2 Scope (code, priority order)
1. `docs/TENANT_ISOLATION.md` (new/changed, security-critical)
2. `docs/data-map.md` (changed, security-critical regression check)
3. `docs/EVIDENCE_INDEX.md` (changed)
4. `README.md` (changed)
5. `docs/FAILURE_MODES.md` (changed)
6. `tests/test_endpoints.py` (changed, adversarial tenant boundary)
7. `tests/test_approval_flow.py` (changed, cross-tenant approval boundary)
8. `tests/test_middleware.py` (changed, invalid slug/HMAC boundary)
9. `tests/test_webhook_service.py` (changed, signature-before-side-effects boundary)
10. `tests/test_isolation.py` (changed, RLS read/write regression)
11. `tests/test_rbac.py` (changed, tenant-scoped JWT and role regression)
12. `tests/test_auth_service.py` (changed, tenant-scoped auth regression)
13. `tests/test_secrets_store.py` (changed, per-tenant secret regression)
14. `tests/test_cost_ledger.py` (changed, tenant cost isolation regression)
15. `app/db.py` (security-critical regression check for transaction-local RLS context)
16. `app/middleware/signature.py` (security-critical regression check)
17. `app/middleware/auth.py` (security-critical regression check)
18. `app/services/auth_service.py` (security-critical regression check)
19. `app/services/approval_service.py` (security-critical regression check)
20. `app/approval_store.py` (security-critical regression check)
21. `app/secrets_store.py` (security-critical regression check)
22. `app/cost_ledger.py` (security-critical regression check)
23. `app/routers/analytics.py` (regression check for tenant-scoped audit reads and carry-forward route drift)
24. `app/routers/tickets.py` (regression check for carry-forward route drift)
25. `app/routers/clusters.py` (regression check for carry-forward route drift)
26. `docs/ARCHITECTURE.md` (changed/targeted refresh candidate for T21/T22)
27. `docs/load-profile.md` (regression check for measured vs target language)

## Cycle Type
Full — Phase 5 is complete with T18–T20 reviewed at a security phase boundary, and the next graph action moves into Phase 6 deployment-readiness work.

## Notes for PROMPT_3
Consolidation should focus on claim consistency before T21/T22: tenant-isolation proof must stay bounded to local/test-backed controls, CODE-1/CODE-2 should be confirmed closed, and Phase 6 should include the targeted `docs/ARCHITECTURE.md` refresh recommended for compose, health, deployment-readiness, eval/evidence wording, and stale system snapshot drift.
