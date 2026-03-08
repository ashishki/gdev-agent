# REVIEW_REPORT — Cycle 3

_Date: 2026-03-04 · Scope: T09–T12 · Previous: `archive/PHASE3_REVIEW.md`_

## Executive Summary

- **Stop-Ship: No**
- T09–T12 complete: isolation tests, CostLedger, read endpoints, agent registry CRUD
- Baseline: 111 pass, 12 skip (integration tests require Docker)
- All P0 from Cycle 2 closed
- 1 P1 open (RS256 vs HS256) — requires architecture decision, not Codex
- 4 P2 open — carry-forward, non-blocking

## P0 Issues

_None_

## P1 Issues

### P1-1 — ADR-003 mandates RS256; HS256 implemented

Evidence: `app/config.py:45-46` (`jwt_algorithm = "HS256"`), `docs/adr/003-rbac-design.md`
Impact: No key rotation without redeploy; no JWKS for external verifiers.
Fix options:
- Accept HS256 → update ADR-003 + add `RuntimeError` if `jwt_secret < 32 bytes`
- Implement RS256 → `RS_PRIVATE_KEY`/`RS_PUBLIC_KEY`, JWKS endpoint, rotation docs
Decision required from architecture (not Codex).

## P2 Issues

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| P2-1 | Redis keys not tenant-namespaced (doc vs code drift) | `data-map.md §3`, `app/dedup.py`, `app/approval_store.py` | Open — Phase 5 |
| P2-6 | `agent.py` imports `HTTPException` from fastapi (layer violation) | `app/agent.py`, `app/main.py` | Open — deferred |
| P2-9 | `_run_blocking()` duplicated in `store.py` and `agent.py` | both files | Open — deferred |
| P2-10 | `get_settings()` requires `ANTHROPIC_API_KEY` at import time | `app/main.py`, `tests/conftest.py` | Open — documented |

## Carry-Forward Status

| ID | Sev | Description | Status |
|----|-----|-------------|--------|
| P0-1 | P0 | Cross-tenant isolation in /approve | ✅ Closed (T09, FIX-1) |
| P0-2 | P0 | EventStore RLS bypass | ✅ Closed (SET LOCAL in store.py) |
| P1-1 | P1 | RS256 vs HS256 | 🔴 Open |
| P1-2 | P1 | RateLimitMiddleware sync Redis | ✅ Closed |
| P1-3 | P1 | Double Settings at module load | ✅ Closed |
| P1-4 | P1 | Budget bypass on missing tenant_id | ✅ Closed (FIX-1) |
| P2-3 | P2 | KB_BASE_URL not in URL_ALLOWLIST | ✅ Closed (FIX-5) |
| P2-5 | P2 | N8N.md dangling reference | ✅ Closed (FIX-4) |
| P2-7 | P2 | reviewer stored raw (PII) | ✅ Closed (FIX-2) |
| P2-8 | P2 | Duplicate config cost fields | ✅ Closed (FIX-3) |

## Stop-Ship Decision

**No.** All P0 closed. P1-1 requires architecture decision. System stable at current baseline.
Next: T13 · EmbeddingService.
