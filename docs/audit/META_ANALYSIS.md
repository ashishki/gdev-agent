---
# META_ANALYSIS — Cycle 12
_Date: 2026-03-20 · Type: full_

## Project State

Phase 11 (PORT-1, PORT-2, PORT-3, PORT-4) complete. All tasks through Phase 11 done.
Next: deep review — no new implementation tasks queued; pending Phase 12 scope definition or external release.
Baseline: 198 pass, 0 fail, 0 skip (with Docker/PG); 184 pass, 14 skip (without PG).
Delta from Cycle 11: +31 pass, -14 fail, +14 skip → **repo green** (FIX-H resolved all REG-2 regressions, CODE-1/CODE-2/CODE-3 closed).

## Open Findings

| ID | Sev | Description | Files | Status |
|----|-----|-------------|-------|--------|
| CODE-4 | P2 | `auth_ratelimit:{email_hash}` absent from data-map §3; key is intentionally global (no tenant prefix) but undocumented | `app/middleware/rate_limit.py:129`, `docs/data-map.md §3` | Open — add to data-map |
| CODE-5 | P2 | Silent broad `except Exception:` in `_fetch_embeddings` swallows ANN fallback with no `LOGGER.warning` or `exc_info` | `app/jobs/rca_clusterer.py:276` | Open (carry-forward Cycles 8–11) |
| CODE-6 | P2 | `run_eval()` non-async path has no `check_budget()` call — budget bypass via CLI or direct invocation | `eval/runner.py:51-110` | Open (carry-forward) |
| CODE-7 | P2 | `_fetch_raw_texts_admin` uses `gdev_admin` session with no tenant_id assertion guard | `app/jobs/rca_clusterer.py:427-440` | Open (carry-forward) |
| CODE-8 | P2 | `auth_ratelimit:{email_hash}` absent from data-map §3 | `app/middleware/rate_limit.py:129` | Open — see CODE-4 |
| CODE-9 | P2 | `run_blocking` raises untyped `data` — `raise data  # type: ignore[misc]`; no `BaseException` narrowing | `app/utils.py:34` | Open (carry-forward) |
| CODE-12 | P2 | Module-level `get_settings()` coupling requires `ANTHROPIC_API_KEY` at import time | `app/main.py:223` | Open (carry-forward as P2-10) |
| ARCH-5 | P2 | `/metrics` JWT exemption: inline comment present (FIX-F); ADR-004 and ARCHITECTURE.md security section not updated | `app/main.py:371`, `docs/adr/004-observability-stack.md` | Open (partial) |
| ARCH-6 | P2 | `GET /clusters/{cluster_id}` returns members via timestamp heuristic, not persisted membership — CLU-1 marked ✅ but finding should be re-verified | `app/routers/clusters.py:151-175` | Open — verify CLU-1 acceptance criteria met |
| ARCH-9 | P2 | Business logic embedded in `/webhook` and `/approve` handlers in `app/main.py` | `app/main.py:255-366` | Open — deferred Phase 10+ |
| CODE-12 / P2-10 | P2 | Import-time `get_settings()` requires API key at import | `app/main.py:223` | Open — no change |
| CODE-12 (P3) | P3 | No unit test for `_fetch_embeddings` ANN fallback exception branch | `tests/test_rca_clusterer.py` | Open (carry-forward Cycles 8–11) |

## PROMPT_1 Scope (architecture)

- Phase 10 delivery (CLI-1, CLU-1, CLU-2): verify `scripts/cli.py` Typer CLI exists and satisfies acceptance criteria; confirm `rca_cluster_members` migration 0003 exists and CLU-1 actually replaced the timestamp heuristic in `app/routers/clusters.py`
- Phase 11 delivery (PORT-1–PORT-4): verify README Mermaid diagram renders, `docs/WORKFLOW.md` exists, `scripts/demo.py` exits 0, ADR-006 MCP evaluation decision documented
- ARCH-9 (webhook/approve business logic in main.py): assess scope and risk for extracting to a service layer; estimate as a Phase 12 SVC-4 task
- ARCH-5 (metrics JWT exemption docs gap): confirm whether ADR-004 and ARCHITECTURE.md were updated by DOC-1/DOC-2 or remain stale
- Contract rules A–L in CODEX_PROMPT v3.11: verify no new call sites have introduced `SET LOCAL` parameterized binding, session-level SET, or other contract violations introduced during Phase 10–11 work

## PROMPT_2 Scope (code, priority order)

1. `app/routers/clusters.py` (CLU-1 closure — verify heuristic replaced; ARCH-6 re-check)
2. `scripts/cli.py` (new — Phase 10 CLI-1; full review: command coverage, mocked DB/Redis, no real API calls)
3. `tests/test_cli.py` (new — verify CliRunner tests for all commands)
4. `alembic/versions/0003_cluster_membership.py` (new — verify upgrade/downgrade complete, RLS policy correct)
5. `app/jobs/rca_clusterer.py` (changed — CLU-1 membership write; CODE-5 silent exception; CODE-7 admin session guard)
6. `app/main.py` (ARCH-9 webhook/approve logic; CODE-12 import-time coupling — regression check)
7. `eval/runner.py` (CODE-6 — budget bypass in non-async path; still open)
8. `app/utils.py` (CODE-9 — untyped re-raise; still open)
9. `docs/adr/004-observability-stack.md` (ARCH-5 — verify metrics JWT exemption documented)
10. `docs/data-map.md §3` (CODE-4/CODE-8 — verify auth_ratelimit key documented)
11. `app/middleware/rate_limit.py` (CODE-4 — cross-reference with data-map)
12. `scripts/demo.py` (PORT-3 — verify script is runnable and exits 0 against Docker Compose)

## Cycle Type

Full — Phase 11 complete, all implementation tasks done. This is a post-completion review cycle; no new feature tasks are queued. Focus is on verifying Phase 10–11 deliverables meet acceptance criteria and confirming remaining P2 findings from Cycles 8–11 that have been carried forward without resolution. Any newly discovered issues should be catalogued as Phase 12 candidates.

## Notes for PROMPT_3

- All P0 and P1 findings from Cycle 11 (CODE-1/REG-2, CODE-2/ARCH-7-new, CODE-3/ARCH-8-new) are confirmed CLOSED per CODEX_PROMPT v3.11; do not re-open without fresh evidence.
- ARCH-6 (CLU-1 heuristic → persisted membership) is marked ✅ in tasks.md but the finding table in CODEX_PROMPT still shows it as OPEN. PROMPT_3 must confirm CLU-1 acceptance criterion 4 ("GET /clusters/{id} returns tickets from DB, not timestamp heuristic") is satisfied in the actual code before closing.
- The six P2 carry-forwards (CODE-4, CODE-5, CODE-6, CODE-7, CODE-9, CODE-12) have survived 3+ cycles with no resolution; PROMPT_3 should recommend either a targeted FIX-I to close them in batch or formally defer to a hypothetical v2 scope with an explicit rationale.
- ARCH-9 (business logic in /webhook and /approve in app/main.py) is a clear SVC-4 candidate for Phase 12; PROMPT_3 should scope it as a new task if architecture review confirms the pattern matches the prior SVC-1/SVC-2 extraction model.
- Baseline is now 198 pass / 0 fail / 0 skip (PG) and 184 pass / 14 skip (no PG). PROMPT_3 should confirm this matches pytest output from the current HEAD and update CODEX_PROMPT if a discrepancy is found.
---
