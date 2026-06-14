# gdev-agent - Compact Session State

Version: 6.1
Date: 2026-06-14
Status: portfolio-hardening-active

Full historical prompt archived at
`docs/archive/portfolio-cleanup-2026-05-29/CODEX_PROMPT_full_2026-03-21.md`.

## Current Phase

Phase 6 remediation after Cycle 18 deployment-readiness deep review.

Business goal: close Phase 6 stop-ship findings before hiring-packaging work.

Cycle 18 found no P0 issues, but Phase 7 is blocked until Compose/env runtime
contracts and evidence-state drift are fixed.

## Current State

- Product: multi-tenant support/AI backend showcase.
- Portfolio role: employer-facing engineering case.
- Development mode: portfolio hardening, evidence packaging, reliability/eval
  proof, and bounded deployment-readiness work.
- Baseline: `.venv/bin/python -m pytest tests/ -q` -> 278 passed, 0 skipped,
  45 warnings (orchestrator-verified before T22 docs/config hardening).
- Phase 6 review: `docs/archive/PHASE18_REVIEW.md` -> Stop-Ship: Yes for
  Phase 7 advancement; no P0 findings.
- Historical product roadmap is complete enough; this cycle must not reopen
  speculative product scope.
- The task graph was rebuilt from the human-provided
  `GDEV_AGENT_PORTFOLIO_HARDENING_PLAN.md`.

## Active Inputs

- `README.md`
- `docs/PROJECT_PLAN.md`
- `docs/tasks.md`
- `docs/ARCHITECTURE.md`
- `docs/IMPLEMENTATION_CONTRACT.md`
- `docs/DEMO.md`
- `docs/EVIDENCE_INDEX.md`
- `docs/EVALUATION.md`
- `docs/PORTFOLIO_REVIEW_GUIDE.md`
- `docs/load-profile.md`
- `docs/observability.md`

─── Fix Queue ───

1. `FIX-P6-1` [P1] — Compose Runtime And Env Contract Repair.
   - Fix Compose migration/health path, live LLM env interpolation,
     `.env.example` parser mismatch, cost env names, `.dockerignore`, and
     focused tests.
   - Validation: `pytest tests/test_cli.py tests/test_config.py -q`,
     `ruff check app/ tests/ scripts/`, and
     `docker-compose config >/tmp/gdev-compose-config.txt`.
2. `FIX-P6-2` [P1] — Phase 6 Evidence And Architecture Alignment.
   - Align README CI eval wording, phase statuses, architecture/spec security
     and readiness wording, backup command notes, boundary validation evidence,
     and stale prompt root examples.
   - Validation: documented `rg` checks in `docs/tasks.md`.

## Open Findings

| ID | Sev | Description | Status |
|----|-----|-------------|--------|
| CODE-1 | P2 | Broad `except Exception` handlers re-raise without required `LOGGER.error(..., exc_info=True)` logs. | Closed - tenant-safe `exc_info=True` logs added in `app/routers/clusters.py` and `app/approval_store.py`; covered by `tests/test_endpoints.py` and `tests/test_redis_approval_store.py` |
| CODE-18-1 | P1 | Compose migration/health path is unreliable because migration check loads live LLM settings and agent healthcheck uses `curl` not present in the image. | Open - fix in `FIX-P6-1` |
| CODE-18-2 / ARCH-18-2 | P1 | README documents `.env` live LLM key override, but Compose hard-codes `ANTHROPIC_API_KEY: test-key`. | Open - fix in `FIX-P6-1` |
| ARCH-18-1 | P1 | `.env.example` list values do not match runtime comma-split parsing for approval categories and URL allowlist. | Open - fix in `FIX-P6-1` |
| META-18-1 | P1 | README and task graph contradict completed CI eval gate and completed phase state. | Open - fix in `FIX-P6-2` |
| CODE-2 / ARCH-1 | P2 | Ticket, analytics, and cluster read APIs still embed query, pagination, metrics, error mapping, and response assembly logic in route handlers. | Open - extract read workflows into services; non-blocking for T21 |
| CODE-18-3 | P2 | Cost env vars are documented under names runtime settings do not read. | Open - fix in `FIX-P6-1` |
| CODE-18-4 | P2 | Docker build context can include untracked local secrets because `.dockerignore` is missing. | Open - fix in `FIX-P6-1` |
| CODE-3 / ARCH-2 / ARCH-HARDEN-1 / ARCH-18-3 | P2 | Current-state architecture/spec docs conflict with current security/readiness behavior. | Open - fix in `FIX-P6-2` |
| ARCH-3 | P2 | `docs/spec.md` auth and production-secret assumptions lag current JWT/HMAC architecture. | Open - fix in `FIX-P6-2` |
| ARCH-4 | P2 | Phase 6 deployment-readiness architecture was documented in T21/T22, but Cycle 18 found runtime/config regressions. | Open - close after `FIX-P6-1` and `FIX-P6-2` |
| CODE-4 / prior CODE-3 | P3 | `docs/load-profile.md` mixes target assumptions or estimates with measured local/synthetic load evidence. | Open - clarify measured-vs-target language before final packaging |
| CODE-18-5 | P3 | `docs/prompts/ORCHESTRATOR.md` still has stale `/home/gdev/gdev-agent` examples. | Open - fix in `FIX-P6-2` |

## Next Task

`FIX-P6-1`: Compose Runtime And Env Contract Repair.

## Rules

- Do not turn this into a full SaaS product.
- Do not add a chat UI.
- Do not add open-ended multi-agent behavior.
- Do not claim production readiness without external deployment or users.
- Keep public docs focused on product and engineering evidence.
- Do not add AI-development process notes to the public README unless they
  directly explain evidence quality.
- Do not rewrite commit history from this agent session.
- Run only documented smoke/test commands when changing setup or code.
- Preserve tenant isolation, audit, approval, and eval boundaries.
