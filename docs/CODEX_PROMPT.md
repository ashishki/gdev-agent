# gdev-agent - Compact Session State

Version: 6.7
Date: 2026-06-14
Status: portfolio-hardening-active

Full historical prompt archived at
`docs/archive/portfolio-cleanup-2026-05-29/CODEX_PROMPT_full_2026-03-21.md`.

## Current Phase

Phase 7 - Hiring Packaging.

Business goal: package the evidence so hiring managers and technical
interviewers can review quickly and drill down when needed.

Phase 6 remediation is complete. T23 one-page case study, T24 architecture
diagram asset, T25 demo recording checklist, and T26 resume bullets are
complete. Remaining Phase 7 packaging must keep all claims backed by runnable
or documented evidence.

## Current State

- Product: multi-tenant support/AI backend showcase.
- Portfolio role: employer-facing engineering case.
- Development mode: portfolio hardening, evidence packaging, reliability/eval
  proof, bounded deployment-readiness work, and hiring evidence packaging.
- Baseline: `.venv/bin/python -m pytest tests/ -q` -> 278 passed, 0 skipped,
  45 warnings (orchestrator-verified before T22 docs/config hardening).
- Current validation: `.venv/bin/python -m pytest tests/ -q` -> 285 passed,
  0 skipped, 45 warnings after `FIX-P6-1`.
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

─── Fix Queue ─── (empty — proceed to phase queue)

No P0/P1 findings are open.

## Open Findings

| ID | Sev | Description | Status |
|----|-----|-------------|--------|
| CODE-1 | P2 | Broad `except Exception` handlers re-raise without required `LOGGER.error(..., exc_info=True)` logs. | Closed - tenant-safe `exc_info=True` logs added in `app/routers/clusters.py` and `app/approval_store.py`; covered by `tests/test_endpoints.py` and `tests/test_redis_approval_store.py` |
| CODE-18-1 | P1 | Compose migration/health path is unreliable because migration check loads live LLM settings and agent healthcheck uses `curl` not present in the image. | Closed - `FIX-P6-1` decoupled migration settings, switched healthcheck to Python stdlib, and covered with `tests/test_cli.py` / `tests/test_config.py` |
| CODE-18-2 / ARCH-18-2 | P1 | README documents `.env` live LLM key override, but Compose hard-codes `ANTHROPIC_API_KEY: test-key`. | Closed - `FIX-P6-1` uses Compose interpolation for `LLM_MODE` and `ANTHROPIC_API_KEY` |
| ARCH-18-1 | P1 | `.env.example` list values do not match runtime comma-split parsing for approval categories and URL allowlist. | Closed - `FIX-P6-1` normalizes `.env.example` and accepts comma/JSON list parsing |
| META-18-1 | P1 | README and task graph contradict completed CI eval gate and completed phase state. | Closed - `FIX-P6-2` aligns README CI/eval wording and phase status |
| CODE-2 / ARCH-1 | P2 | Ticket, analytics, and cluster read APIs still embed query, pagination, metrics, error mapping, and response assembly logic in route handlers. | Open - extract read workflows into services; non-blocking for T21 |
| CODE-18-3 | P2 | Cost env vars are documented under names runtime settings do not read. | Closed - `FIX-P6-1` documents `LLM_*_RATE_PER_1K` and keeps legacy `ANTHROPIC_*_COST_PER_1K` aliases |
| CODE-18-4 | P2 | Docker build context can include untracked local secrets because `.dockerignore` is missing. | Closed - `FIX-P6-1` adds `.dockerignore` exclusions and coverage |
| CODE-3 / ARCH-2 / ARCH-HARDEN-1 / ARCH-18-3 | P2 | Current-state architecture/spec docs conflict with current security/readiness behavior. | Closed - `FIX-P6-2` refreshes architecture/spec security, readiness, and LLM secret behavior |
| ARCH-3 | P2 | `docs/spec.md` auth and production-secret assumptions lag current JWT/HMAC architecture. | Closed - `FIX-P6-2` aligns protected REST JWT, signed webhook, metrics, and bounded readiness assumptions |
| ARCH-4 | P2 | Phase 6 deployment-readiness architecture was documented in T21/T22, but Cycle 18 found runtime/config regressions. | Closed - `FIX-P6-1` and `FIX-P6-2` close runtime/config and docs drift |
| CODE-4 / prior CODE-3 | P3 | `docs/load-profile.md` mixes target assumptions or estimates with measured local/synthetic load evidence. | Open - clarify measured-vs-target language before final packaging |
| CODE-18-5 | P3 | `docs/prompts/ORCHESTRATOR.md` still had stale legacy root examples. | Closed - root examples now use `/home/ashishki/Documents/dev/ai-stack/projects/gdev-agent` |

## Next Task

`T27`: Final Evidence Audit.

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
