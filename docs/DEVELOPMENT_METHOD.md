# Development Methodology

_v1.0 · gdev-agent · AI-assisted development workflow._

---

## Overview

gdev-agent is built using a structured AI-assisted development loop. A human architect defines tasks and reviews decisions. Specialized AI agents implement and review code. An orchestrator drives the loop.

```
Human defines tasks → Orchestrator drives loop → Codex implements → Review pipeline → Fix → Loop
```

The human is responsible for:
- Defining phases and task acceptance criteria in `docs/tasks.md`
- Resolving blockers (`[!]` tasks)
- Making architectural decisions (ADRs)
- Approving stop-ship decisions

The orchestrator is responsible for:
- Reading state and deciding what to do next
- Spawning the right agent at the right time
- Updating state documents
- Stopping on blockers and reporting clearly

---

## Entry Point

There is one way to start the development cycle:

```
Paste docs/prompts/ORCHESTRATOR.md to Claude Code (main session).
No variables. No setup. Just paste and send.
```

The orchestrator reads `docs/CODEX_PROMPT.md` and `docs/tasks.md` to determine current state, then drives the loop autonomously.

---

## Agent Roles

| Role | Prompt | Tool | Produces |
|---|---|---|---|
| **Orchestrator** | `docs/prompts/ORCHESTRATOR.md` | Main Claude Code session | Loop control, state updates |
| **Codex** (implementer) | Built into Orchestrator | `Bash` → `codex exec -s workspace-write` | Code, tests, file changes |
| **Codex** (fixer) | Built into Orchestrator | `Bash` → `codex exec -s workspace-write` | Fixes for P0/P1 findings |
| **Strategy** | `docs/prompts/PROMPT_S_STRATEGY.md` | Agent tool (general-purpose) | `STRATEGY_NOTE.md` |
| **META** | `docs/audit/PROMPT_0_META.md` | Agent tool (general-purpose) | `META_ANALYSIS.md` |
| **ARCH** | `docs/audit/PROMPT_1_ARCH.md` | Agent tool (general-purpose) | `ARCH_REPORT.md` |
| **CODE** | `docs/audit/PROMPT_2_CODE.md` | Agent tool (general-purpose) | Findings (in-session) |
| **CONSOLIDATED** | `docs/audit/PROMPT_3_CONSOLIDATED.md` | Agent tool (general-purpose) | `REVIEW_REPORT.md` + patches |

**Tool split rule:** Codex writes code via `codex exec`. Review agents reason and analyze via Agent tool. Never mix.

**Codex invocation:**
```bash
PROMPT=$(cat /tmp/gdev_codex_prompt.txt)
cd /home/artem/dev/ai-stack/projects/gdev-agent && codex exec -s workspace-write "$PROMPT"
```
Always pass prompt as a variable — not via stdin (`-`).

**Context rule:** Load only what each role needs. Extra context degrades accuracy and increases cost.

---

## The Loop

```
[Session start]
  Orchestrator reads CODEX_PROMPT.md + tasks.md
                │
  Phase boundary? ──► Strategy Review (PROMPT_S)
                │
  Fix Queue? ──► Codex implements fixes (in order)
                │
  Next task ──► Codex implements
                │
  ┌─────────────┴──────────────────────────────┐
  │                                            │
  Regular task                          Phase boundary
  + non-security                        OR security-critical
       │                                        │
  Light Review                          Deep Review
  (1 agent, 6 checks)           (META → ARCH → CODE → CONSOLIDATED)
       │                                        │
  Issues? → Codex fix             P0? → Codex fix (max 2 attempts)
       │                                        │
  Pass                             Archive REVIEW_REPORT
  └─────────────────────────────────────────────┘
                │
          Loop back
```

---

## Two-Tier Review System

| Tier | When | Agent calls | Token cost | Output |
|---|---|---|---|---|
| **Light** | After each task within a phase | 1 | Low | Pass / issue list → Codex fixes |
| **Deep** | Phase boundary or security-critical task | 4 (sequential) | High | REVIEW_REPORT + tasks/CODEX patches + archive |

**Light review checks (6 items):**
SEC-1 SQL parameterization · SEC-2 Tenant isolation (SET LOCAL) · SEC-3 No PII in logs
SEC-4 No hardcoded secrets · SEC-5 Async correctness · SEC-6 Auth/RBAC on new routes
+ CF: Implementation Contract rules A–I

**Deep review triggers:**
- All tasks in a phase are complete (phase boundary)
- Last task touched: auth, middleware, RLS, tenant isolation, secrets
- 5+ P2 findings open for 3+ cycles

**Skip all review:** doc-only patches, test-only changes, dependency bumps.

---

## Deep Review Pipeline (4 steps, sequential)

Each step produces a file that the next step reads. Never parallelize.

```
PROMPT_0_META    →  META_ANALYSIS.md    (state snapshot, scope definition)
      ↓
PROMPT_1_ARCH    →  ARCH_REPORT.md      (architecture drift vs ARCHITECTURE.md + ADRs)
      ↓
PROMPT_2_CODE    →  findings (in-session) (security + code review, 8 SEC + 3 QUAL checks)
      ↓
PROMPT_3_CONSOLIDATED → REVIEW_REPORT.md + tasks.md patch + CODEX_PROMPT.md patch
```

---

## Finding Lifecycle

```
Open → In Progress → Mitigated → Closed
```

A finding is **Closed** only when:
1. PROMPT_3 verified the fix in code (specific `file:line` cited)
2. A test exists that would fail without the fix

Self-closing without code verification is forbidden.

---

## Severity Tiers

| Severity | Meaning | Blocks |
|---|---|---|
| P0 | Release blocker / security / data loss | Stop-ship — fix before any next task |
| P1 | Correctness or reliability issue | Must have task entry in tasks.md |
| P2 | Important, non-blocking | Carries forward with ID |
| P3 | Improvement / tech debt | Carries forward with ID |

---

## Phase Boundaries

A new phase starts when: all tasks in the previous phase are `✅` and the next task is in a different phase.

At every phase boundary:
1. Run the Strategy Review (PROMPT_S) → `STRATEGY_NOTE.md`
2. Archive `REVIEW_REPORT.md` → `docs/archive/PHASE{N}_REVIEW.md`
3. Update `docs/audit/AUDIT_INDEX.md`
4. Then start Codex on the first task of the new phase

---

## tasks.md Status Legend

| Symbol | Meaning |
|---|---|
| `[ ]` | Not started |
| `[~]` | Implemented, pending review |
| `[x]` or `✅` | Complete — implemented and reviewed |
| `[!]` | Blocked — needs human input |

---

## CODEX_PROMPT.md Version Management

`docs/CODEX_PROMPT.md` is the session handoff document. PROMPT_3 updates it at the end of every review cycle.

Content:
- **Session Handoff** — completed tasks, baseline, Fix Queue, next task
- **Open Findings table** — ID, severity, status, evidence

The immutable implementation rules are in `docs/IMPLEMENTATION_CONTRACT.md` (separate file, not re-read every session).

Bump the version (v3.N → v3.N+1) on every CONSOLIDATED run.

---

## Document Versioning Policy

| Document | Policy |
|---|---|
| `CODEX_PROMPT.md` | Bump minor version each review cycle |
| `REVIEW_REPORT.md` | Overwritten each cycle; previous → `archive/PHASE{N}_REVIEW.md` |
| `ARCHITECTURE.md` | Bump version on structural change; all PRs must keep current |
| `IMPLEMENTATION_CONTRACT.md` | Immutable without ADR + Architecture approval |
| `adr/` | Append-only; existing ADRs not edited |
| `archive/` | Write-only; nothing deleted |

---

## Manual Overrides

**Re-run a specific review cycle:**
1. Open `docs/audit/REVIEW_REPORT.md` — already contains the previous cycle
2. Re-paste the orchestrator; it will re-run based on current state

**Force-skip the review for one iteration:**
Start the session with:
```
Run orchestrator. Skip review cycle this iteration — implement next task only.
```

**Re-run a specific phase:**
1. In `docs/tasks.md`, change phase tasks back to `[ ]`
2. Re-paste the orchestrator

**Run one review step manually:**
```
Read docs/audit/PROMPT_0_META.md and execute it.
```
(Same for PROMPT_1, PROMPT_2, PROMPT_3.)

---

## Resuming After a Stop

The orchestrator is stateless — it re-reads from files on every session.

After a blocker:
1. Resolve the `[!]` task manually (or clear the mark)
2. Re-paste `docs/prompts/ORCHESTRATOR.md`
3. Orchestrator picks up from current state

---

_Reference: `docs/prompts/ORCHESTRATOR.md` for the runnable loop._
_Reference: `docs/audit/review_pipeline.md` for review protocol detail._
_Reference: `docs/IMPLEMENTATION_CONTRACT.md` for Codex implementation rules._
