# ARCH_REPORT — Cycle 18

_Date: 2026-06-14 · Scope: Phase 6 deployment-readiness architecture_

## Verdict

Phase 6 is directionally honest but not ready to feed Phase 7 packaging.

## Boundary Checks

| Area | Result | Notes |
|------|--------|-------|
| Production-readiness claims | PASS | `docs/DEPLOYMENT_READINESS.md` correctly says the repo is not production ready or externally deployed. |
| Secrets checklist | PARTIAL | Required-vs-optional intent is documented, but `.env.example` and runtime parser do not fully align. |
| Compose migration/readiness | FAIL | Migration check and healthcheck are coupled to unrelated runtime assumptions. |
| Backup/restore notes | PASS-WITH-GAP | Notes are local/pilot only; backup directory creation is missing from the copy command path. |
| Architecture/security docs | DRIFT | `/approve`, `/health`, webhook secrets, and live LLM requirements are stale in architecture/readme surfaces. |

## Findings

### ARCH-18-1 [P1] — `.env.example` List Syntax Does Not Match Runtime Parser

`APPROVAL_CATEGORIES=["billing","account_access"]` and
`URL_ALLOWLIST=["kb.example.com"]` are JSON-like strings, but
`app/config.py` only comma-splits env strings. Category routing and URL
allowlist behavior can therefore be wrong in a local run using `.env.example`.

Evidence: `.env.example:24`, `.env.example:34`, `app/config.py:65`,
`app/config.py:86`, `app/agent.py:532`.

### ARCH-18-2 [P1] — Documented Live LLM Compose Override Is Not Wired

README tells reviewers to set `ANTHROPIC_API_KEY` in `.env` for live LLM
behavior, but Compose hard-codes `ANTHROPIC_API_KEY: test-key` for the agent
service. `LLM_MODE` is interpolated; the provider key is not.

Evidence: `README.md:116`, `docker-compose.yml:41`, `docker-compose.yml:43`.

### ARCH-18-3 [P2] — Architecture Security And Readiness Text Is Stale

`docs/ARCHITECTURE.md` still contains older `/approve`, `/health`, webhook
secret, and unconditional live-key language that does not match current runtime
behavior.

Evidence: `docs/ARCHITECTURE.md:605`, `docs/ARCHITECTURE.md:840`,
`docs/ARCHITECTURE.md:849`, `docs/ARCHITECTURE.md:868`,
`app/main.py:257`, `app/main.py:306`, `app/services/approval_service.py:112`,
`app/config.py:103`.

### ARCH-18-4 [P3] — Backup Command Assumes `./backups` Exists

The local backup command copies into `./backups/gdev.dump` without creating the
directory first.

Evidence: `docs/DEPLOYMENT_READINESS.md:95`, `docs/DEPLOYMENT_READINESS.md:97`.

## Recommended Fix Scope

Fix runtime/config issues first, then refresh docs. Do not start `T23` until the
Phase 6 remediation packet is committed and pushed.
