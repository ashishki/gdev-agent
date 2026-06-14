# gdev-agent - Project Plan

Status: active portfolio hardening cycle
Role: employer-facing engineering showcase
Priority: P1 evidence, reliability, eval, observability, and packaging hardening

## Strategic Role

`gdev-agent` should remain a polished portfolio project. Its value is showing
production-style backend/AI orchestration engineering: multi-tenancy, input
guardrails, human approval, audit trail, cost controls, observability, and test
coverage.

Bounded status: the current stack is pilot-grade/local evidence. It is not a
production SaaS, and this plan does not claim external deployment, live tenants,
or production operations.

The current hardening cycle is not product expansion. It is evidence work:
repeatable demos, eval baselines, failure-mode proof, tenant-isolation proof,
load/observability reports, deployment-readiness notes, and hiring packaging.

The project does not need more product features unless real production load or
real operator feedback appears.

## Near-Term Roadmap

### P0 - Evidence Path

- Keep README clean and employer-facing.
- Add a one-click evidence path for architecture, demo, eval, load, failure
  modes, tenant isolation, observability, deployment readiness, and known
  limits.
- Keep claims specific and bounded.

### P1 - Reliability And Eval Proof

- Make the demo deterministic without paid model calls.
- Expand eval data and add regression gates for unsafe behavior.
- Add named failure modes with tests and runbook responses.
- Publish local load and observability evidence.

### P2 - Hiring Packaging

- Add a case study, architecture visual, demo recording checklist, and measured
  resume bullets.
- Keep packaging grounded in committed proof, not marketing claims.

### Phase 6 - Deployment Readiness Without Overclaiming

- Make local Compose setup verifiable with explicit Postgres/Redis health
  dependencies and a migration check command:
  `python scripts/cli.py migrations check`.
- Treat `GET /health` as app-process liveness. Local Compose readiness depends
  on healthy Postgres/Redis plus successful migration verification and seeding.
- Document secrets, backup/restore, and production-like config as readiness
  knowledge only; do not claim production SaaS readiness without an external
  deployment and users.

### Future Only With Real Load

- Reopen product development only if real support traffic, real tenants, or real
  game-studio operator feedback exists.

## Development Tasks

- The active AI-loop task graph lives in `docs/tasks.md`.
- Keep README and project-plan claims bounded to pilot/local evidence until a
  real deployment and real users exist.
- No new speculative product features.
- Do not reintroduce process/tooling details that distract from the portfolio
  story.
- If changes are needed, keep them small, tested, and employer-readable.

## Stop Conditions

- Stop any work that turns the project into a fake product without real users.
- Stop any claim that implies production readiness without external deployment
  or users.
