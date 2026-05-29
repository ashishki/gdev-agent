# gdev-agent Tasks

Status: portfolio-frozen
Last updated: 2026-05-29

Full historical implementation task graph is archived at
`docs/archive/portfolio-cleanup-2026-05-29/tasks_full_2026-03-21.md`.

This active file contains only portfolio-maintenance work. Do not revive this
project as an active product unless a human explicitly reopens it.

## Active Tasks

### GDEV-PF-01: README And Demo Packaging Review

Owner: Human + Codex
Priority: P1
Status: planned

Objective: |
  Keep the project interview-ready: product description, architecture, setup,
  and demo path should be clear without internal process noise.

Acceptance-Criteria:
  - README explains product value, architecture, setup, and demo path.
  - Demo instructions match current prerequisites.
  - No new product feature is opened.

### GDEV-PF-02: Verification Smoke Pass

Owner: Codex
Priority: P1
Status: planned

Objective: |
  Run documented smoke/test commands and record breakage as maintenance
  findings.

Acceptance-Criteria:
  - Test/lint command results are recorded.
  - Failures are triaged as setup drift, dependency drift, or regression.
  - No unrelated refactor is made during smoke verification.

### GDEV-PF-03: Dependency And Security Maintenance

Owner: Codex
Priority: P2
Status: planned

Objective: |
  Keep dependencies and security posture reasonable for a portfolio project.

Acceptance-Criteria:
  - Updates are limited to installability or security needs.
  - Changes are verified with the documented smoke path.
  - Public docs remain focused on product/engineering value.
