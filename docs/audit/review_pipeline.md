# Review Pipeline

_v1.0 · gdev-agent_

## When to Run

- Iteration complete (one or more tasks from `tasks.md` done)
- Baseline regression detected
- New ADR required
- Planned phase gate

## Pipeline

```
PROMPT_0_META → PROMPT_1_ARCH → PROMPT_2_CODE → PROMPT_3_CONSOLIDATED
      ↓                ↓                               ↓
META_ANALYSIS.md   ARCH_REPORT.md              REVIEW_REPORT.md
                                               + patch tasks.md
                                               + patch CODEX_PROMPT.md
```

## Steps

**Step 0 — META** (`PROMPT_0_META.md`)
Read: `tasks.md`, `CODEX_PROMPT.md`, `audit/REVIEW_REPORT.md`
Output: `META_ANALYSIS.md` — current phase, baseline, open findings, scope for steps 1–2, cycle type (full / targeted)

**Step 1 — ARCH** (`PROMPT_1_ARCH.md`)
Read: `META_ANALYSIS.md`, `ARCHITECTURE.md`, `spec.md`, `adr/`
Output: `ARCH_REPORT.md` — PASS/DRIFT/VIOLATION per component, ADR compliance, doc patches needed

**Step 2 — CODE** (`PROMPT_2_CODE.md`)
Read: `META_ANALYSIS.md`, `dev-standards.md`, `data-map.md`, scope files
Output: inline findings (fed to step 3) — SQL, tenant isolation, PII, async, auth, tests

**Step 3 — CONSOLIDATED** (`PROMPT_3_CONSOLIDATED.md`)
Read: all step 0–2 outputs, `tasks.md`, `CODEX_PROMPT.md`
Output: `REVIEW_REPORT.md` + `tasks.md` patch + `CODEX_PROMPT.md` patch

## Stop-Ship Rule

P0 in REVIEW_REPORT → phase blocked. Fix + re-run before next Codex task.
P1 → must have entry in `tasks.md`. Does not block phase.

## End-of-Cycle

Move `REVIEW_REPORT.md` → `archive/PHASE{N}_REVIEW.md` before starting the next cycle.
Update `AUDIT_INDEX.md` cycle history.
