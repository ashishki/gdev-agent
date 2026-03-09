# gdev-agent docs

Multi-tenant AI triage service · FastAPI + Claude tool_use + Redis + PostgreSQL + n8n

This documentation set describes a delivered Phase 1-7 implementation:
multi-tenant support automation, approval workflows, analytics APIs, RCA clustering,
eval endpoints, load-test assets, and full-stack deployment support.

## Navigation

| Need | Start here |
|------|-----------|
| Understand the system | `spec.md` → `ARCHITECTURE.md` → `adr/` |
| Current status / next task | `CODEX_PROMPT.md` → `tasks.md` |
| Latest review findings | `audit/REVIEW_REPORT.md` |
| Run a review cycle | `audit/review_pipeline.md` |
| AI agent roles & process | `AI_FRAMEWORK.md` |
| Show the project to a potential customer | `../README.md` |

## File Map

```
docs/
├── CODEX_PROMPT.md          implementation agent prompt (source of truth)
├── tasks.md                 task graph
├── AI_FRAMEWORK.md          AI roles, context protocol, finding lifecycle
├── spec.md / ARCHITECTURE.md / PLAN.md
├── data-map.md / dev-standards.md / observability.md / N8N.md
├── llm-usage.md / load-profile.md / agent-registry.md
├── adr/                     001–005 architecture decisions
├── audit/                   review cycle artifacts
│   ├── AUDIT_INDEX.md       artifact registry
│   ├── review_pipeline.md   pipeline reference
│   ├── PROMPT_0_META.md     step 0: state snapshot
│   ├── PROMPT_1_ARCH.md     step 1: architecture drift
│   ├── PROMPT_2_CODE.md     step 2: code & security
│   ├── PROMPT_3_CONSOLIDATED.md  step 3: final report
│   ├── META_ANALYSIS.md     [output, overwritten each cycle]
│   ├── ARCH_REPORT.md       [output, overwritten each cycle]
│   └── REVIEW_REPORT.md     [output, overwritten each cycle — canonical findings]
├── archive/                 phase snapshots (permanent)
└── devlog/
```

## Current implementation status

Completed phases:

- **Phase 1:** schema, migrations, async DB, RLS
- **Phase 2:** tenant registry, per-tenant webhook secrets, auth boundary
- **Phase 3:** approval hardening, cost ledger, isolation coverage
- **Phase 4:** read APIs, analytics, agent registry
- **Phase 5:** embeddings, RCA background job, cluster APIs
- **Phase 6:** security hardening and protected endpoint flow
- **Phase 7:** eval REST endpoints, per-tenant baselines, load testing, Docker updates

Current local baseline:

- `pytest tests/ -q` → `144 passed, 13 skipped`
- `ruff check app/ tests/` → passing
- `ruff format --check app/ tests/` → passing
- `mypy app/` → passing
