# Review Pipeline

_v1.1 · gdev-agent_

## When to Run

**Full cycle (all 4 steps):**
- Phase gate — a logical group of tasks is complete
- Pre-deploy / pre-release
- After security-critical changes (auth, RLS, tenant isolation, middleware)
- ≥3 tasks accumulated since last review

**Targeted (PROMPT_2_CODE only):**
- Hotfix of a specific module
- Closing a carry-forward P1 finding

**Skip entirely:**
- Doc-only patches
- Test-only changes with no logic change
- Dependency bumps with no API change

## Phase Boundaries (review triggers)

Phases are defined in `tasks.md`. Codex works within a phase without interruption.
Review runs at the phase boundary, not between individual tasks.

```
Phase 4: T13–T15  →  Cycle 4 review
Phase 5: T16–T18  →  Cycle 5 review
```

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

## How to Run

Open a new Claude session in the project root. One of two approaches:

**Step-by-step (recommended — review output between steps):**
```
1. "Read docs/audit/PROMPT_0_META.md and execute it."
2. "Read docs/audit/PROMPT_1_ARCH.md and execute it."
3. "Read docs/audit/PROMPT_2_CODE.md and execute it."
4. "Read docs/audit/PROMPT_3_CONSOLIDATED.md and execute it."
```

**One-shot (faster, less control):**
```
"Run the full review cycle: execute PROMPT_0_META.md, then PROMPT_1_ARCH.md,
then PROMPT_2_CODE.md, then PROMPT_3_CONSOLIDATED.md sequentially.
Write each output file before proceeding to the next step."
```

Use one session — context accumulates across steps and step 3 needs step 0–2 outputs.

## Handoff to Codex After Review

After PROMPT_3 completes, send Codex this command (new session):

```
Review complete. Read docs/CODEX_PROMPT.md.
Implement everything in Fix Queue first (in order).
Then proceed with the Phase queue.
```

PROMPT_3 writes the Fix Queue into CODEX_PROMPT.md automatically.
If Fix Queue is empty, Codex goes straight to the phase queue.

## End-of-Cycle

Move `REVIEW_REPORT.md` → `archive/PHASE{N}_REVIEW.md` before starting the next cycle.
Update `AUDIT_INDEX.md` cycle history.
