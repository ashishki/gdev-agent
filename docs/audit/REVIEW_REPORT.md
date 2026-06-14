# REVIEW_REPORT — Cycle 18
_Date: 2026-06-14 · Scope: T21–T22_

## Executive Summary

- Stop-Ship: Yes, for Phase 7 advancement.
- No P0 findings were found.
- Four P1 findings block the transition to `T23`: Compose migration/health
  reliability, Compose live LLM env override, `.env.example` parser mismatch,
  and public evidence/task-state contradictions.
- Six P2 findings should be addressed in the same remediation window or carried
  explicitly before final packaging.
- Phase 6 deployment-readiness language is correctly bounded and does not claim
  production readiness.
- Next graph action: complete `FIX-P6-1`, then `FIX-P6-2`, then rerun/close the
  Phase 6 review gate before starting `T23`.

## P0 Issues

None.

## P1 Issues

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-18-1 | Compose migration/health path is unreliable: `migrate` runs `scripts/cli.py migrations check` through full app settings with no LLM env, and the agent healthcheck uses `curl` even though the image does not install it. | `docker-compose.yml:25`, `docker-compose.yml:58`, `Dockerfile:1`, `Dockerfile:4`, `scripts/cli.py:339`, `app/config.py:103` | Open |
| CODE-18-2 / ARCH-18-2 | Documented live LLM Compose path is broken because README says `.env` can set `ANTHROPIC_API_KEY`, but Compose hard-codes `test-key`. | `README.md:116`, `docker-compose.yml:42`, `docker-compose.yml:43` | Open |
| ARCH-18-1 | `.env.example` uses JSON-like list values, but runtime env parsing only comma-splits strings; approval categories and URL allowlist can be misparsed. | `.env.example:24`, `.env.example:34`, `app/config.py:65`, `app/config.py:86`, `app/agent.py:532` | Open |
| META-18-1 | Public evidence state contradicts completed work: README says CI eval gate is planned/incomplete while the graph and workflow show it implemented. Older phase statuses also remain stale. | `README.md:26`, `README.md:226`, `docs/tasks.md:49`, `docs/tasks.md:136`, `docs/tasks.md:335`, `.github/workflows/ci.yml:66` | Open |

## P2 Issues

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| CODE-18-3 | Cost env vars are documented as `ANTHROPIC_*_COST_PER_1K`, but runtime settings read `LLM_*_RATE_PER_1K` field names unless aliases are added. | `.env.example:18`, `README.md:156`, `app/config.py:30`, `app/agent.py:683` | Open |
| CODE-18-4 | Docker build context can include untracked local secrets because the repo has no `.dockerignore`. | `Dockerfile:5`, `.gitignore:17` | Open |
| ARCH-18-3 | Architecture/security docs are stale for `/approve`, `/health`, webhook secrets, and live LLM startup requirements. | `docs/ARCHITECTURE.md:605`, `docs/ARCHITECTURE.md:840`, `docs/ARCHITECTURE.md:849`, `docs/ARCHITECTURE.md:868`, `app/main.py:257`, `app/main.py:306`, `app/services/approval_service.py:112`, `app/config.py:103` | Open |
| META-18-2 | Completed phase statuses are stale in `docs/tasks.md`, weakening the graph as a reviewer-facing source. | `docs/tasks.md:49`, `docs/tasks.md:136`, `docs/tasks.md:499`, `docs/tasks.md:598` | Open |
| META-18-3 | Boundary validation evidence is under-recorded after T22. | `docs/CODEX_PROMPT.md:27`, `docs/tasks.md:721`, `docs/tasks.md:749` | Open |
| ARCH-18-4 | Backup docs assume `./backups` exists. | `docs/DEPLOYMENT_READINESS.md:95`, `docs/DEPLOYMENT_READINESS.md:97` | Open |

## P3 Issues

| ID | Description | Files | Status |
|----|-------------|-------|--------|
| META-18-4 | Carry-forward wording still says measured-vs-target cleanup can happen during Phase 6 even though Phase 6 is now complete. | `docs/CODEX_PROMPT.md:61` | Open |
| CODE-18-5 | Prompt docs still contain stale legacy-root examples. | `docs/prompts/ORCHESTRATOR.md:27`, `docs/prompts/ORCHESTRATOR.md:59`, `docs/prompts/ORCHESTRATOR.md:117` | Open |

## Carry-Forward Status

| ID | Sev | Description | Status | Change |
|----|-----|-------------|--------|--------|
| CODE-1 | P2 | Broad exception handlers missing tenant-safe `exc_info=True` logs. | Closed | Fixed in `3748125`; covered by endpoint and Redis approval-store tests. |
| CODE-2 / ARCH-1 | P2 | Ticket, analytics, and cluster read APIs still embed read workflow logic in route handlers. | Open | Carried; not touched by Phase 6. |
| CODE-3 / ARCH-2 / ARCH-HARDEN-1 | P2 | Current-state docs conflict with Cycle 17 evidence/security behavior. | Open | Partially reduced by T22 README baseline updates; architecture/spec drift remains and is folded into `FIX-P6-2`. |
| ARCH-3 | P2 | `docs/spec.md` auth and production-secret assumptions lag current JWT/HMAC architecture. | Open | Carried into `FIX-P6-2`. |
| ARCH-4 | P2 | Phase 6 deployment-readiness architecture was not documented. | Closed-with-regressions | T21/T22 added readiness docs, but Cycle 18 found runtime/config issues that must be fixed before Phase 7. |
| CODE-4 / prior CODE-3 | P3 | `docs/load-profile.md` mixes target assumptions with measured local/synthetic evidence. | Open | Carried; should be clarified before final packaging. |

## Stop-Ship Decision

Yes — do not start `T23` yet. The repo remains acceptable as local/pilot
evidence, but Phase 7 packaging would currently amplify broken Compose/env
assumptions and stale evidence state. Fix `FIX-P6-1` and `FIX-P6-2`, validate,
commit, push, and then close the Phase 6 gate.
