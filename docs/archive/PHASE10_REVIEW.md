---
# REVIEW_REPORT — Cycle 12
_Date: 2026-03-21 · Scope: Phase 10 (CLI-1, CLU-1, CLU-2) + Phase 11 (PORT-1–PORT-4) · Baseline: 198 pass, 0 fail, 0 skip_

## Executive Summary

- Stop-Ship: **No** — repo is green; 198 pass / 0 fail. No P0 or P1 findings this cycle. All Phase 10–11 acceptance criteria confirmed satisfied in code.
- Phase 10 complete: `scripts/cli.py` (CLI-1), `rca_cluster_members` migration (CLU-1, migration file confirmed as `0005_cluster_membership.py`), `GET /clusters/{id}/tickets` endpoint (CLU-2). FIX-H (Cycle 11 stop-ship) fully resolved — baseline rose from 167 pass / 14 fail to 198 pass / 0 fail.
- Phase 11 complete: README Mermaid diagram (PORT-1), `docs/WORKFLOW.md` (PORT-2), `scripts/demo.py` (PORT-3), ADR-006 MCP evaluation (PORT-4 — skip decision documented).
- ARCH-6 (CLU-1 timestamp heuristic) confirmed CLOSED: `app/routers/clusters.py:203–220` queries `rca_cluster_members` via DB, not timestamp heuristic. Code verified.
- ARCH-12 (P1-1 / RS256 vs HS256) confirmed CLOSED: `docs/adr/003-rbac-design.md:53` explicitly accepts HS256 for v1. No code conflict; phantom finding retired.
- Three new P2 findings this cycle (CODE-13, CODE-14, CODE-15) catalogued for Phase 12 resolution. No new P0 or P1.
- Six long-running P2 carry-forwards (CODE-4/CODE-8, CODE-5, CODE-6, CODE-9, ARCH-5, ARCH-9) remain open; recommended Phase 12 batch fix (FIX-I) to close them in a single pass. Formal defer to v2 is the alternative if scope is not approved.

---

## P0 Issues

_None this cycle._

---

## P1 Issues

_None this cycle._

---

## P2 Issues

### New Findings (Cycle 12)

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-13 | `list_clusters` and `get_cluster` route handlers lack OTel span and Prometheus metrics | `app/routers/clusters.py:96-152`, `app/routers/clusters.py:155-225` | Open — add spans + counters |
| CODE-14 | `_create_tenant` calls `_set_tenant_ctx` before INSERT — tenant UUID does not exist yet; RLS SET LOCAL references a non-existent row | `scripts/cli.py:83-101` | Open — move `_set_tenant_ctx` call to after INSERT |
| CODE-15 | `test_cli.py` missing error-path tests: `tenant disable` not-found, `budget check` exhausted, `budget check` not-found | `tests/test_cli.py` | Open — add negative-path test cases |

### Carry-Forward Open P2

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-4 / CODE-8 | `auth_ratelimit:{email_hash}` absent from `docs/data-map.md §3`; key is global by design (no tenant prefix) but undocumented | `app/middleware/rate_limit.py:129`, `docs/data-map.md §3` | Open — 5+ cycles |
| CODE-5 | Silent broad `except Exception:` in `_fetch_embeddings` swallows ANN fallback — no `LOGGER.warning` or `exc_info` | `app/jobs/rca_clusterer.py:276` | Open — carry-forward Cycles 8–12 |
| CODE-6 | `run_eval()` non-async path has no `check_budget()` call — budget bypass via CLI or direct invocation | `eval/runner.py:51-110` | Open — carry-forward |
| CODE-9 | `run_blocking` raises untyped `data` — `raise data  # type: ignore[misc]`; no `BaseException` narrowing | `app/utils.py:34` | Open — carry-forward |
| ARCH-5 | `/metrics` JWT exemption: inline comment present (FIX-F); `docs/adr/004-observability-stack.md` and `ARCHITECTURE.md` security section not updated | `app/main.py:371`, `docs/adr/004-observability-stack.md` | Open (partial) — doc patches identified |
| ARCH-9 | Business logic embedded in `/webhook` and `/approve` handlers — tenant resolution, dedup, HMAC check inline in `app/main.py` | `app/main.py:255-366` | Open — SVC-4 candidate Phase 12 |

### Doc Patch P2 Items

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| DOC-PATCH-1 | ADR-004: add `/metrics` JWT exemption note under §Instrumentation Scope | `docs/adr/004-observability-stack.md` | Open — ARCH-5 resolution |
| DOC-PATCH-2 | ADR-003: add RS256 deferral note in §Consequences closing P1-1 ambiguity | `docs/adr/003-rbac-design.md` | Open |
| DOC-PATCH-3 | `ARCHITECTURE.md §2.1`: add Phase 10–11 deliverables (CLI-1, PORT-2, PORT-3, PORT-4) | `docs/ARCHITECTURE.md` | Open — ARCH-11 |
| DOC-PATCH-4 | `ARCHITECTURE.md §2.2`: add `scripts/cli.py`, `scripts/demo.py`, `docs/WORKFLOW.md`, `docs/adr/006-mcp-server-evaluation.md` to layout tree | `docs/ARCHITECTURE.md` | Open — ARCH-11 |
| DOC-PATCH-5 | `docs/data-map.md §3`: add `auth_ratelimit:{email_hash}` Redis key row | `docs/data-map.md` | Open — CODE-4/CODE-8/ARCH-10 |

---

## P3 Issues

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-12 (P3) | No unit test for `_fetch_embeddings` ANN fallback exception branch | `tests/test_rca_clusterer.py` | Open — carry-forward Cycles 8–12 |
| ARCH-11 | `ARCHITECTURE.md §2.1` and `§2.2` not updated with Phase 10–11 deliverables | `docs/ARCHITECTURE.md` | Open — low risk, informational |

---

## Carry-Forward Status

| ID | Sev | Description | Status | Change |
|----|-----|-------------|--------|--------|
| CODE-1 (Cycle 11) | P0 | `SET LOCAL` parameterized binding rejected by asyncpg | CLOSED ✅ FIX-H | Resolved Cycle 11; 14 regressions cleared |
| CODE-2 (Cycle 11) | P1 | `AuthService` imports `JSONResponse` — transport type in service layer | CLOSED ✅ FIX-H | Resolved Cycle 11 |
| CODE-3 (Cycle 11) | P1 | `POST /auth/logout` and `POST /auth/refresh` not registered | CLOSED ✅ FIX-H | Resolved Cycle 11 |
| REG-2 | P1 | 14 test failures — asyncpg `SET LOCAL` root cause | CLOSED ✅ FIX-H | Baseline now 198 pass / 0 fail |
| CODE-4 / CODE-8 | P2 | `auth_ratelimit:{email_hash}` absent from data-map §3 | Open | No change — 5th cycle carry-forward |
| CODE-5 | P2 | Silent exception in `_fetch_embeddings` | Open | No change — 5th cycle carry-forward |
| CODE-6 | P2 | `run_eval()` non-async path no `check_budget()` | Open | No change |
| CODE-7 | P2 | `_fetch_raw_texts_admin` cross-tenant guard | CLOSED ✅ | Guard present at `app/jobs/rca_clusterer.py:472-484` — confirmed in code |
| CODE-9 | P2 | `run_blocking` untyped re-raise | Open | No change |
| CODE-12 | P2 | Module-level `get_settings()` coupling | CLOSED ✅ | `app/main.py` lifespan refactor confirmed — no import-time coupling |
| ARCH-5 | P2 | `/metrics` JWT exemption undocumented in ADR-004 | Open (partial) | Doc patches identified; code comment present |
| ARCH-6 | P2 | Cluster detail used timestamp heuristic | CLOSED ✅ CLU-1 | `clusters.py:203–220` queries `rca_cluster_members`; DB-backed |
| ARCH-9 | P2 | Business logic in `/webhook` and `/approve` | Open | SVC-4 Phase 12 candidate; not regressed |
| ARCH-11 | P3 | ARCHITECTURE.md not updated with Phase 10–11 deliverables | Open | Low risk; informational |
| ARCH-12 | P2 | ADR-003 RS256 vs HS256 ambiguity | CLOSED ✅ | HS256 accepted per ADR-003:53; P1-1 superseded |
| ARCH-13 | P2 | SET LOCAL f-string: Contract-G satisfied | No violation | No new call sites detected; vigilance note only |
| CODE-12 (P3) | P3 | No unit test for `_fetch_embeddings` ANN fallback | Open | No change |
| P1-1 / ARCH-1 | P1 | RS256 vs HS256 conflict | CLOSED ✅ | ADR-003 §Consequences accepts HS256 for v1 |
| P2-10 | P2 | Import-time `get_settings()` | CLOSED ✅ | Resolved — same as CODE-12 lifespan fix |

---

## Resolved This Cycle

| Finding | Resolution | Evidence |
|---------|------------|----------|
| CODE-7 | `_fetch_raw_texts_admin` cross-tenant guard now present | `app/jobs/rca_clusterer.py:472-484` — tenant_id assertion confirmed |
| CODE-12 | Module-level `get_settings()` coupling resolved | `app/main.py` lifespan; no import-time coupling |
| ARCH-6 | CLU-1 heuristic replaced; `get_cluster()` queries `rca_cluster_members` | `app/routers/clusters.py:203–220` — DB-backed confirmed |
| ARCH-12 / P1-1 | ADR-003 RS256 vs HS256 ambiguity — finding was phantom | `docs/adr/003-rbac-design.md:53` explicitly accepts HS256 for v1 |

---

## Stop-Ship Decision

**No.** Repo is green: 198 pass / 0 fail / 0 skip (with PG); 184 pass / 14 skip (without PG). No P0 or P1 findings exist. Three new P2 findings (CODE-13, CODE-14, CODE-15) are actionable for Phase 12. Six carry-forward P2 findings are candidates for a Phase 12 batch fix (FIX-I); if Phase 12 scope is not approved, a formal v2-defer decision with rationale should be recorded in tasks.md.

---

_Next: archive this file to `docs/audit/archive/CYCLE12_REVIEW.md` before Cycle 13 begins._
