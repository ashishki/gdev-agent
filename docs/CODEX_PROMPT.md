# gdev-agent - Compact Session State

Version: 5.3
Date: 2026-06-12
Status: portfolio-hardening-active

Full historical prompt archived at
`docs/archive/portfolio-cleanup-2026-05-29/CODEX_PROMPT_full_2026-03-21.md`.

## Current Phase

Phase 5 - Tenant Isolation And Security Proof.

Business goal: back every multi-tenancy claim with concrete docs, adversarial
examples, and tests.

Phase exit criteria: reviewer can find and run tenant-isolation proof from README.

## Current State

- Product: multi-tenant support/AI backend showcase.
- Portfolio role: employer-facing engineering case.
- Development mode: portfolio hardening, evidence packaging, reliability/eval
  proof, and bounded deployment-readiness work.
- Historical product roadmap is complete enough; this cycle must not reopen
  speculative product scope.
- The task graph was rebuilt from the human-provided
  `GDEV_AGENT_PORTFOLIO_HARDENING_PLAN.md`.

## Active Inputs

- `README.md`
- `docs/PROJECT_PLAN.md`
- `docs/tasks.md`
- `docs/ARCHITECTURE.md`
- `docs/IMPLEMENTATION_CONTRACT.md`
- `docs/DEMO.md`
- `docs/EVIDENCE_INDEX.md`
- `docs/EVALUATION.md`
- `docs/PORTFOLIO_REVIEW_GUIDE.md`
- `docs/load-profile.md`
- `docs/observability.md`

## Fix Queue

Empty.

## Open Findings

| ID | Sev | Description | Status |
|----|-----|-------------|--------|
| ARCH-HARDEN-1 | P2 | `docs/ARCHITECTURE.md` eval summary still references the old 25-case/basic metric shape after T07-T10. | Open - doc patch, non-blocking |

## Next Task

`T18`: Tenant Isolation Evidence Document.

## Rules

- Do not turn this into a full SaaS product.
- Do not add a chat UI.
- Do not add open-ended multi-agent behavior.
- Do not claim production readiness without external deployment or users.
- Keep public docs focused on product and engineering evidence.
- Do not add AI-development process notes to the public README unless they
  directly explain evidence quality.
- Do not rewrite commit history from this agent session.
- Run only documented smoke/test commands when changing setup or code.
- Preserve tenant isolation, audit, approval, and eval boundaries.
