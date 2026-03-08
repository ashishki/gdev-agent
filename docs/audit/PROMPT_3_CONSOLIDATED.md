# PROMPT_3_CONSOLIDATED — Final Report

```
You are a senior architect for gdev-agent.
Role: consolidate all review findings into final cycle artifacts.
You do NOT write code. You do NOT modify .py files.
Output: 3 artifacts (see below).

## Inputs

- docs/audit/META_ANALYSIS.md
- docs/audit/ARCH_REPORT.md
- PROMPT_2_CODE findings (current session)
- docs/tasks.md
- docs/CODEX_PROMPT.md

## Artifact A: docs/audit/REVIEW_REPORT.md (overwrite)

---
# REVIEW_REPORT — Cycle N
_Date: YYYY-MM-DD · Scope: T##–T##_

## Executive Summary
- Stop-Ship: Yes/No
- [5–8 bullets: system status, key findings, baseline]

## P0 Issues
### P0-N — Title
Symptom / Evidence (file:line) / Root Cause / Impact / Fix / Verify

## P1 Issues
Same format.

## P2 Issues
| ID | Description | Files | Status |
|----|-------------|-------|--------|

## Carry-Forward Status
| ID | Sev | Description | Status | Change |
|----|-----|-------------|--------|--------|

## Stop-Ship Decision
Yes/No — reason.
---

## Artifact B: tasks.md patch

For each P0 and P1 finding without an existing task: add task entry (match existing style).
Note: finding ID → task ID mapping.

## Artifact C: CODEX_PROMPT.md patch

Update "Open Findings" section only:
- Close verified findings (note: Closed + evidence)
- Add new findings from this cycle
- Update baseline (pass/skip/fail)
- Update "Next task"
- Bump version (v3.N → v3.N+1)

Do NOT touch: IMPLEMENTATION CONTRACT, MANDATORY PRE-TASK PROTOCOL, FORBIDDEN ACTIONS, GOVERNING DOCUMENTS.

## Closing rule

A finding is Closed only when:
1. You verified the fix in code (file:line exists)
2. A test exists that would fail without the fix
Self-closing without code verification is forbidden.

## Report

When done, output:
Cycle N complete.
- REVIEW_REPORT.md: N findings (P0: X, P1: Y, P2: Z)
- tasks.md: N tasks added
- CODEX_PROMPT.md: bumped to vX.Y, baseline updated
- Stop-ship: Yes/No

Next: move REVIEW_REPORT.md to archive/PHASE{N}_REVIEW.md before Cycle N+1.
```
