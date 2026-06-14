# gdev-agent - Compact Session State

Version: 5.8
Date: 2026-06-14
Status: portfolio-hardening-active

Full historical prompt archived at
`docs/archive/portfolio-cleanup-2026-05-29/CODEX_PROMPT_full_2026-03-21.md`.

## Current Phase

Phase 6 - Deployment Readiness Without Overclaiming.

Business goal: prove setup, migration, health, secrets, and recovery are
understood while keeping deployment claims honest.

Phase exit criteria: fresh-clone local setup is reliable and deployment docs
state known limits clearly.

## Current State

- Product: multi-tenant support/AI backend showcase.
- Portfolio role: employer-facing engineering case.
- Development mode: portfolio hardening, evidence packaging, reliability/eval
  proof, and bounded deployment-readiness work.
- Baseline: `.venv/bin/python -m pytest tests/ -q` -> 272 passed, 0 skipped,
  45 warnings (orchestrator-verified after T20 adversarial boundary tests).
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

─── Fix Queue ─── (empty — proceed to phase queue)

No P0/P1 findings are open.

## Open Findings

| ID | Sev | Description | Status |
|----|-----|-------------|--------|
| CODE-1 | P2 | Broad `except Exception` handlers re-raise without required `LOGGER.error(..., exc_info=True)` logs. | Open - add tenant-safe error logs in `app/routers/clusters.py` and `app/approval_store.py` |
| CODE-2 / ARCH-1 | P2 | Ticket, analytics, and cluster read APIs still embed query, pagination, metrics, error mapping, and response assembly logic in route handlers. | Open - extract read workflows into services; non-blocking for T21 |
| CODE-3 / ARCH-2 / ARCH-HARDEN-1 | P2 | Current-state docs conflict with Cycle 17 evidence and security behavior, including stale test/eval counts and legacy webhook/approval semantics. | Open - refresh README and `docs/ARCHITECTURE.md` before final packaging |
| ARCH-3 | P2 | `docs/spec.md` auth and production-secret assumptions lag current JWT/HMAC architecture. | Open - align spec with protected REST JWT, JWT-exempt signed webhooks, network-scoped metrics, and bounded readiness claims |
| ARCH-4 | P2 | Phase 6 deployment-readiness architecture is not yet documented. | Open - cover compose migration checks, health/readiness/liveness, secrets, backup/restore, production-like config, and known limits in T21/T22 |
| CODE-4 / prior CODE-3 | P3 | `docs/load-profile.md` mixes target assumptions or estimates with measured local/synthetic load evidence. | Open - clarify measured-vs-target language during Phase 6 or final packaging |

## Next Task

`T21`: Compose Migration And Health Hardening.

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
