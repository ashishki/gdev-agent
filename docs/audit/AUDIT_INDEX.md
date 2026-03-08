# Audit Index

_v1.0 · gdev-agent_

## Artifact Policy

| Artifact | Policy |
|----------|--------|
| `PROMPT_*.md` | Canonical prompts — reused each cycle, updated only when process changes |
| `META_ANALYSIS.md`, `ARCH_REPORT.md`, `REVIEW_REPORT.md` | Overwritten each cycle (current state) |
| `archive/PHASE{N}_REVIEW.md` | Permanent snapshot — move REVIEW_REPORT.md here before next cycle |

## Review Schedule (phase-gated)

Reviews run at phase boundaries, not between individual tasks.

| Cycle | Phase | Tasks | Trigger | Status |
|-------|-------|-------|---------|--------|
| 1 | Phase 1 | T01–T04 | Phase 1 gate | ✅ Closed 2026-03-04 |
| 2 | Phase 2 | T05–T08 | Phase 2 gate | ✅ Closed 2026-03-04 |
| 3 | Phase 3 | T09–T12 | Phase 3 gate | ✅ Closed 2026-03-04 · 1 P1 open |
| 4 | Phase 4 | T13–T15 | Phase 4 gate | ⬜ Pending |
| 5 | Phase 5 | T16–T18 | Phase 5 gate | ⬜ Pending |
| 6 | Phase 6 | T19–T21 | Phase 6 gate | ⬜ Pending |
| 7 | Phase 7 | T22–T24 | Phase 7 gate | ⬜ Pending |

## Archive

| File | Cycle | Date |
|------|-------|------|
| `archive/PHASE1_REVIEW.md` | 1 | 2026-03-04 |
| `archive/PHASE2_REVIEW.md` | 2 | 2026-03-04 |
| `archive/PHASE2_FIX_PACKET.yaml` | 2 | 2026-03-04 |
| `archive/PHASE3_REVIEW.md` | 3 | 2026-03-04 |
| `archive/PHASE3_FIX_PACKET.yaml` | 3 | 2026-03-04 |
