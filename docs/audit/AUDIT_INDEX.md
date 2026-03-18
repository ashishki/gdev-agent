# Audit Index

_v1.1 · gdev-agent_
_Automated operation: `docs/prompts/ORCHESTRATOR.md` manages archiving automatically._

## Artifact Policy

| Artifact | Policy |
|----------|--------|
| `PROMPT_*.md` | Canonical prompts — reused each cycle, updated only when process changes |
| `prompts/ORCHESTRATOR.md` | Single entry point for automated loop — read-only except for version bumps |
| `prompts/PROMPT_S_STRATEGY.md` | Strategy prompt — run at phase boundaries |
| `META_ANALYSIS.md`, `ARCH_REPORT.md`, `REVIEW_REPORT.md` | Overwritten each cycle (current state) |
| `STRATEGY_NOTE.md` | Overwritten each phase boundary |
| `archive/PHASE{N}_REVIEW.md` | Permanent snapshot — orchestrator moves REVIEW_REPORT.md here automatically |

## Review Schedule (phase-gated)

Reviews run at phase boundaries, not between individual tasks.

| Cycle | Phase | Tasks | Trigger | Status |
|-------|-------|-------|---------|--------|
| 1 | Phase 1 | T01–T04 | Phase 1 gate | ✅ Closed 2026-03-04 |
| 2 | Phase 2 | T05–T08 | Phase 2 gate | ✅ Closed 2026-03-04 |
| 3 | Phase 3 | T09–T12 | Phase 3 gate | ✅ Closed 2026-03-04 · 1 P1 open |
| 4 | Phase 4 | T13–T15 | Phase 4 gate | ✅ Closed 2026-03-08 |
| 5 | Phase 5 | T16–T18 | Phase 5 gate | ✅ Closed 2026-03-08 |
| 6 | Phase 6 | T19–T21 | Phase 6 gate | ✅ Closed 2026-03-08 |
| 7 | Phase 7 | T22–T24 | Phase 7 gate | ✅ Closed 2026-03-09 (Cycle 8) |
| 8 | Phase 8 | FIX-A–F | Tech debt gate | ✅ Closed 2026-03-18 (Cycle 9) |
| 9 | Phase 9 | SVC-1–3, DOC-1–5 | Service layer gate | ⬜ Pending |

## Archive

| File | Cycle | Date |
|------|-------|------|
| `archive/PHASE1_REVIEW.md` | 1 | 2026-03-04 |
| `archive/PHASE2_REVIEW.md` | 2 | 2026-03-04 |
| `archive/PHASE2_FIX_PACKET.yaml` | 2 | 2026-03-04 |
| `archive/PHASE3_REVIEW.md` | 3 | 2026-03-04 |
| `archive/PHASE3_FIX_PACKET.yaml` | 3 | 2026-03-04 |
| `archive/PHASE4_REVIEW.md` | 4 | 2026-03-08 |
| `archive/PHASE6_REVIEW.md` | 6–7 | 2026-03-09 |
| `archive/PHASE8_REVIEW.md` | 9 | 2026-03-18 |
