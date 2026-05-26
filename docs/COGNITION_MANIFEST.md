# Cognition Manifest - gdev-agent

---
artifact_kind: retrieval_manifest
project: gdev-agent
source_repo: gdev-agent
status: active
canonical: false
generated: false
tags: [multi-tenant, tool-use, eval, cognition]
---

Version: 1.0
Last updated: 2026-05-25

## Purpose

Repo-local map for multi-tenant support triage cognition: approval workflows, RLS, tool-use, eval history, audit trail, observability, and runtime governance.

## Authority Rules

- Canonical repo artifacts win over this manifest.
- Obsidian, generated indexes, and context packets are optional navigation layers.
- RLS, approval, eval, and security decisions require canonical docs or ADRs before implementation relies on them.

## Project Identity

| Field | Value |
|-------|-------|
| Primary shape | Multi-tenant bounded tool-use/agent workflow |
| Governance level | Strict for tenant/security boundaries |
| Runtime tier | T1 compose stack |
| Active profiles | Tool-Use, Agentic workflow, eval/observability |

## Canonical Truth

| Surface | Path | Notes |
|---------|------|-------|
| Architecture | `docs/ARCHITECTURE.md` | System and deployment boundaries |
| Contract | `docs/IMPLEMENTATION_CONTRACT.md` | Implementation rules |
| Task graph | `docs/tasks.md` | Execution history |
| Session state | `docs/CODEX_PROMPT.md` | Current workflow state |
| Eval | `docs/EVALUATION.md`, `eval/cases.jsonl`, `eval/results/last_run.json` | Eval memory |
| Workflow | `docs/WORKFLOW.md`, `docs/WORKFLOW_CANON.md` | Development workflow |
| Audits | `docs/audit/`, `docs/archive/` | Review findings |
| Dev logs | `docs/devlog/` | Handoff context |

## Retrieval Scopes

| Scope | Start here | Include next |
|-------|------------|--------------|
| Tenant/RLS change | architecture, contract | migrations, RLS tests, audit reports |
| Approval workflow | `docs/SESSION_MANAGEMENT.md`, service tests | approval store, n8n docs, review reports |
| Tool-use safety | tool registry/tests | output guard, eval docs, audit reports |
| Eval regression | `docs/EVALUATION.md`, eval results | eval runner, cost ledger, previous review |
| Reviewer packet | task ACs and contract | affected tests, eval docs, audit findings |

## Local/VPS Agent Context Workflow

Agents do not automatically discover the cognition vault. The operator or orchestrator must pass a repo-local manifest, vault project map, or generated context packet path into the agent task.

Expected sibling layout on any machine that runs agents:

```text
ai-stack/
|-- projects/<repo>/
`-- engineering-cognition-vault/
```

Local project work:

```bash
cd ai-stack/engineering-cognition-vault
./scripts/sync_from_projects.sh --no-pull --commit --push
```

Before review, ensure this project has a fresh vault index:

```bash
cd ai-stack/engineering-cognition-vault
./scripts/ensure_fresh_for_project.sh gdev-agent --no-pull --commit --push
```

VPS project work:

1. Commit and push code, docs, evals, ADRs, findings, or postmortems in this repo.
2. Refresh the vault on the machine that owns vault sync:

```bash
cd ai-stack/engineering-cognition-vault
git pull --ff-only
./scripts/sync_from_projects.sh --commit --push
```

If an agent runs on the VPS, clone the vault next to `projects/` and pass packet paths explicitly:

```text
../engineering-cognition-vault/10-projects/<project>.md
../engineering-cognition-vault/90-context-packets/<role>-<project>-<scope>.md
```

Do not write canonical decisions, eval results, or findings directly into the vault. Write them into this repo first, then regenerate the vault.

---

## Known Gaps

| Gap | Impact | Migration step |
|-----|--------|----------------|
| No `docs/DECISION_LOG.md` | Decision recall requires archive search | Add decision log for future architecture/runtime changes |
| No `docs/IMPLEMENTATION_JOURNAL.md` | Handoff context is split across devlog/archive | Add journal if active phase work resumes |
| No `docs/EVIDENCE_INDEX.md` | Proof lookup is manual | Add evidence index for RLS, approvals, output guard, eval baselines |
| No ADR directory | Supersession lineage is weak | Add ADRs only for new major decisions |

## Generated Artifacts

| Artifact | Path | Policy |
|----------|------|--------|
| Cognition index | `generated/cognition/index.json` | Optional generated artifact |
| Context packets | `docs/context-packets/` | Commit only major review/regression packets |

