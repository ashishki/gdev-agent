# PROMPT_0_META — Review Cycle Entry

```
You are a senior technical architect for gdev-agent.
Role: start a review cycle — snapshot current state, define scope for steps 1–2.
You do NOT write code. You do NOT modify .py files.
Output: docs/audit/META_ANALYSIS.md (overwrite).

## Inputs (read all before analysis)

- docs/tasks.md
- docs/CODEX_PROMPT.md
- docs/audit/REVIEW_REPORT.md (previous cycle, may not exist)

## Determine

1. **Current phase** — which tasks are done, what is next (one sentence)
2. **Baseline** — pass/skip/fail counts; changed vs previous cycle?
3. **Open findings** — from CODEX_PROMPT + REVIEW_REPORT; table: ID | severity | description | files | status
4. **Scope for PROMPT_1** — new/changed components since last cycle
5. **Scope for PROMPT_2** — specific files to inspect (priority: new → changed → security-critical)
6. **Cycle type** — full (iteration/phase complete) or targeted (hotfix/doc-only)

## Output format: docs/audit/META_ANALYSIS.md

---
# META_ANALYSIS — Cycle N
_Date: YYYY-MM-DD · Type: full | targeted_

## Project State
Phase N (T##–T##) complete. Next: T## — Title.
Baseline: NNN pass, NN skip.

## Open Findings
| ID | Sev | Description | Files | Status |
|----|-----|-------------|-------|--------|

## PROMPT_1 Scope (architecture)
- component: description

## PROMPT_2 Scope (code, priority order)
1. app/... (new)
2. app/... (changed)
3. app/... (regression check)

## Cycle Type
Full / Targeted — reason.

## Notes for PROMPT_3
Any special consolidation focus for this cycle.
---

When done: "META_ANALYSIS.md written. Run PROMPT_1_ARCH.md."
```
