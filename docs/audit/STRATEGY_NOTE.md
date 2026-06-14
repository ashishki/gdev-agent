# STRATEGY_NOTE — Phase 6
_Date: 2026-06-14_

## Platform Identity
Phase 6 strengthens the system's identity as an AI Support Intelligence Platform by making setup,
migration, health, secrets, and recovery claims verifiable without expanding product scope. T21-T22
are on-identity if they stay framed as local/deployment-readiness proof and explicitly avoid
production-readiness claims.

## Structural Drift Assessment
| Finding | Cycles open | Structural pattern | Action |
|---|---:|---|---|
| ARCH-HARDEN-1 | 3+ | Documentation drift: architecture eval summary trails the implemented dataset and gate | Resolve during Phase 6 documentation work; fold into the architecture/evidence refresh so final packaging does not carry stale quality claims |
| ARCH-1 | <3 | Layer boundary erosion: read/query, pagination, metrics, and response assembly remain in route handlers | Carry forward; non-blocking for T21-T22 because Phase 6 does not touch those read APIs, but schedule service extraction before new read API work |
| ARCH-2 | <3 | System snapshot drift: architecture spec no longer matches current audit, eval, load, observability, and deployment evidence | Modify Phase 6 scope to update `docs/ARCHITECTURE.md` alongside compose, health, and deployment-readiness docs |
| CODE-3 | <3 | Evidence-boundary ambiguity: target assumptions and measured load evidence are mixed | Carry forward into T22 evidence packaging; clarify measured vs target claims before hiring-package review |

## ADR Alignment
| ADR | Conflict | Recommendation |
|---|---|---|
| ADR-001 Storage | No conflict. T21 migration checks and T22 backup/restore notes reinforce Postgres as the durable system of record, with Redis retained for ephemeral coordination. | Proceed; ensure T22 does not imply Redis pending/dedup/rate-limit state is durable business data |
| ADR-003 RBAC | No conflict. T22 secrets and production-like config notes should preserve the accepted HS256/JWT v1 model and document key-rotation limits honestly. | Proceed |
| ADR-004 Observability | No conflict. T21 compose health behavior aligns with the accepted local observability stack, provided health/readiness docs distinguish app liveness from dependency health. | Proceed |
| ADR-005 Orchestration Model | No conflict. Compose dependency hardening must preserve n8n as the retry, approval UI, and workflow boundary rather than moving orchestration into application code. | Proceed |
| ADR-006 MCP Server Evaluation | No conflict. Phase 6 stays on HTTP, compose, and deployment evidence; it does not introduce a second protocol surface. | Proceed |

## Phase Risk
Highest-risk task: T21 — Compose Migration And Health Hardening
Required test: `tests/test_migrations.py` and `tests/test_cli.py` must verify the documented
migration check path reports the current Alembic schema state and fails clearly on migration drift;
`docker compose config >/tmp/gdev-compose-config.txt` must remain a documented validation command.

## Recommendation
Proceed with modification
Modify T21 or T22 to include a targeted `docs/ARCHITECTURE.md` refresh for compose, health,
deployment-readiness, eval/evidence wording, and current system snapshot drift before final packaging.
