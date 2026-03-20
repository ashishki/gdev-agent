# Canonical AI Development Workflow

_v1.0 · 2026-03-20 · Derived from gdev-agent build experience + external references._
_Portable — copy this to any project and adapt roles, phases, and tooling._

---

## Purpose

This document captures the workflow philosophy, structure, and design decisions behind how we
run autonomous AI-driven development loops. It is a reference for bootstrapping the same
process in new projects where roles, stack, and team size may differ.

---

## Source References

### 1. gstack — garrytan/gstack (MIT)

**What it is:** A set of slash commands that turns Claude Code into a virtual engineering team.
Each command is a specialist role: Staff Engineer, QA Lead, Release Engineer, CEO/Product, Designer.

**Core insight borrowed:**
- The sprint is a **process with structured handoffs**, not a bag of tools.
  Each phase feeds its output into the next. The review agent knows what the build agent produced.
- **Role separation enforces quality.** A reviewer who didn't write the code finds bugs
  the author missed. Encode this as explicit separate agents, not a single "do everything" prompt.
- `/document-release` principle: after every ship, docs must be updated in the same cycle,
  not deferred. Stale documentation is a liability.
- `/retro` principle: measure what was shipped. LOC, tests added, findings closed.
  Data beats intuition.

**What we did NOT take:**
- Browser automation (`/browse`, `/qa`) — backend API, no UI to click
- Product/design roles (`/office-hours`, `/plan-ceo-review`, `/design-review`) — roadmap is fixed
- Parallel sprints — single-repo, single-branch development

**Link:** https://github.com/garrytan/gstack

---

### 2. gsamat audit workflow — gist.github.com/gsamat

**What it is:** A `CLAUDE.md` for technical audit of existing systems. Obsidian-based
documentation vault. Research → Discovery → Analysis → Action Points.

**Core insight borrowed:**
- **Session Separation Rule:** never mix building and reviewing in the same agent session.
  Fresh eyes catch what the implementer's context blinds them to.
- **Goals Awareness Rule:** before any analysis, read the project goals. Every finding must
  map to a business concern, not float in technical abstraction.
- **Risk Register vs Insights separation:**
  - Risk Register = specific, actionable bugs with file:line (R001, R002 — IDs never change)
  - Insights = systemic observations, architectural patterns, cross-cutting conclusions
  - Mixing them creates noise; separating them makes prioritisation tractable.
- **ID Stability Rule:** never renumber or delete risk/insight IDs. Mark as "Closed" with
  explanation. Cross-references stay valid across cycles.

**What we did NOT take:**
- Obsidian vault folder structure — we're building, not auditing an external system
- Russian-language documentation — our project docs are English-only
- Per-codebase research template — applies to audit of foreign codebases, not greenfield build

**Link:** https://gist.github.com/gsamat/d2aeb4eaa79260bc5f85ec9056296596

---

## Core Principles

### P1 — Stateless orchestrator, stateful files

The orchestrator re-reads all state from files on every run. No in-memory state survives
between sessions. This makes rate-limit interruptions free: resume = re-paste the orchestrator
prompt. State lives in: task list, CODEX_PROMPT.md, MEMORY.md, audit reports.

### P2 — Build and review are separate sessions

Never implement and review in the same agent invocation. The build agent (Codex) writes code.
A separate review agent reads the output cold. This is the single most reliable way to catch
bugs before they accumulate.

### P3 — Every task needs a test, every fix needs a test

No implementation without a corresponding test. No bug fix without a regression test.
Tests are the only reliable baseline signal across sessions and rate-limit interruptions.

### P4 — Two-tier review

| Tier | When | Cost | Output |
|------|------|------|--------|
| Light | After every 1-2 tasks (non-security) | ~1 agent call | Pass / Issues list |
| Deep | Phase boundary or security-critical change | 4 sequential agents | REVIEW_REPORT, task patches |

Deep review is expensive. Light review runs fast and catches contract violations.
The tier decision is made at the start of each loop iteration.

### P5 — Goals check before build

Before implementing any task, the orchestrator reads the current phase goals.
This prevents drift where the agent optimises for task completion rather than business outcome.

### P6 — Phase report for the human

At every phase boundary, generate a plain-language report:
- What was built and why it matters in the bigger picture
- Test baseline before and after
- Open findings (P1/P2) and their risk to next phase
- Overall health verdict

This is not a status dump. It is an explanation aimed at someone learning, not a senior engineer.

### P7 — Rate-limit resilience

API rate limits are inevitable in long autonomous sessions. The system must:
- Save a checkpoint to memory before stopping (what was done, what is next)
- Resume cleanly from files without needing human re-briefing
- Notify the operator when paused and when resumed

### P8 — Docs updated same cycle

README, ARCHITECTURE, CODEX_PROMPT — updated in the same phase cycle that ships the changes.
No "we'll update docs later." Later never comes in autonomous loops.

---

## Generic Loop Structure

```
┌─────────────────────────────────────────────────────────────┐
│  ORCHESTRATOR (re-read on every run — stateless)             │
└──────────────────────────┬──────────────────────────────────┘
                           │
          ┌────────────────▼────────────────┐
          │  0. STATE CHECK                  │
          │     Read task list + goals       │
          │     Determine: fix queue?        │
          │     Phase boundary?              │
          │     Review tier?                 │
          └────────────────┬────────────────┘
                           │
          ┌────────────────▼────────────────┐
          │  1. GOALS CHECK (phase boundary) │
          │     Read PLAN.md / phase goals   │
          │     Confirm scope before build   │
          └────────────────┬────────────────┘
                           │
          ┌────────────────▼────────────────┐
          │  2. BUILD SESSION                │
          │     Implementer agent (Codex)    │
          │     Writes code + tests          │
          │     Commit after each task       │
          └────────────────┬────────────────┘
                           │
          ┌────────────────▼────────────────┐
          │  3. TEST GATE                    │
          │     pytest — must be green       │
          │     Failed = stop, report        │
          └────────────────┬────────────────┘
                           │
          ┌────────────────▼────────────────┐
          │  4. REVIEW SESSION (separate)    │
          │     Light: contract checklist    │
          │     Deep: META → ARCH → CODE     │
          │            → CONSOLIDATED        │
          └────────────────┬────────────────┘
                           │
          ┌────────────────▼────────────────┐
          │  5. FIX (if issues found)        │
          │     Codex fixer — exact issues   │
          │     Re-run review after fix      │
          └────────────────┬────────────────┘
                           │
          ┌────────────────▼────────────────┐
          │  6. ARCHIVE (deep review only)   │
          │     Copy report to archive       │
          │     Update audit index           │
          └────────────────┬────────────────┘
                           │
          ┌────────────────▼────────────────┐
          │  7. DOC UPDATE (phase boundary)  │
          │     README, ARCHITECTURE, CODEX  │
          │     Update memory checkpoint     │
          └────────────────┬────────────────┘
                           │
          ┌────────────────▼────────────────┐
          │  8. PHASE REPORT (phase boundary)│
          │     Student-friendly summary     │
          │     Tests / findings / health    │
          │     Send via Telegram            │
          └────────────────┬────────────────┘
                           │
          ┌────────────────▼────────────────┐
          │  9. RATE LIMIT CHECKPOINT        │
          │     Save "what's next" to memory │
          │     If 429 → sleep → resume      │
          └────────────────┬────────────────┘
                           │
                    LOOP BACK TO 0
                    (or DONE / BLOCKED)
```

---

## Roles — Generic Definition

Define these for every project. Roles can be merged (one agent covers multiple) or split
(each role is its own specialist with a dedicated prompt file).

| Role | Responsibility | Mandatory? |
|------|---------------|------------|
| **Orchestrator** | Reads state, decides action, spawns agents, updates state | Always |
| **Implementer** | Writes code and tests. Never reviews. | Always |
| **Light Reviewer** | Contract + security checklist on every task | Always |
| **META Analyst** | Scopes deep review: which files, which risks | Phase boundary |
| **Architecture Reviewer** | ADRs, data flow, system-level concerns | Phase boundary |
| **Code Reviewer** | File-level bugs, security, test coverage | Phase boundary |
| **Consolidation Agent** | Synthesises all review output into one report | Phase boundary |
| **Strategy Reviewer** | Phase scope, business alignment, pivot signals | Phase boundary |
| **Report Generator** | Plain-language phase summary for the human | Phase boundary |
| **Doc Updater** | Keeps README, ARCHITECTURE, changelog current | Phase boundary |

**For a solo-dev project:** Orchestrator + Implementer + Light Reviewer is the minimum viable set.
Add Deep Review roles as the codebase grows or risk increases.

**For a team project:** Each role can be a different Claude Code instance running in parallel
(e.g. via Conductor). The shared state is the file system + git.

---

## Adapting to a New Project

Checklist when bootstrapping this workflow in a new repo:

- [ ] Copy `docs/prompts/ORCHESTRATOR.md` — replace project name, paths, and tool invocation
- [ ] Create `docs/CODEX_PROMPT.md` — baseline, Fix Queue, task list summary
- [ ] Create `docs/tasks.md` — full task graph with AC per task
- [ ] Create `docs/IMPLEMENTATION_CONTRACT.md` — project-specific rules (DB patterns, auth rules, etc.)
- [ ] Create `docs/audit/` — AUDIT_INDEX.md, review prompt files (PROMPT_0–3)
- [ ] Set up `scripts/dev_loop.sh` — configure WAIT_SECONDS for your API plan tier
- [ ] Define MEMORY.md structure — user, feedback, project, reference entries
- [ ] Set Telegram bot token + chat ID in `.env` for phase reports
- [ ] Define Light Review checklist — project-specific security checks (SEC-1..N)
- [ ] Define what "phase boundary" means — how phases are delimited in tasks.md

**What changes per project:**
- Role prompts (PROMPT_0–3) — adjust scope and domain language
- Light review checklist (SEC-N) — match the tech stack and threat model
- Phase structure — fewer or more phases, different task types
- Commit convention — adapt to team standard
- Notification channel — Telegram, Slack, email, or none

**What stays the same:**
- Stateless orchestrator (reads from files)
- Build / Review session separation
- Two-tier review (light / deep)
- Test gate before any review
- Phase report for the human
- Rate-limit checkpoint before stopping

---

## Phase Report Format

Generated at every phase boundary. Sent via Telegram (mobile-readable).

```
📦 Phase [N] — [Phase Name] — COMPLETE

What was built:
• [Deliverable 1] — [1-sentence plain English why it matters]
• [Deliverable 2] — [why]
• [Deliverable 3] — [why]

Why this phase matters:
[2-3 sentences in plain English — how this fits the overall system.
Explain as if talking to someone learning software engineering.]

Tests:
• Before: [N] pass / [N] skip
• After:  [N] pass / [N] skip / [N] fail
• New tests added: [N] ([what they cover])

Open issues:
• P1: [N] — [short description of most important one]
• P2: [N] — [examples]
• Blocking next phase: Yes/No

Overall health: ✅ Green / ⚠️ Caution / 🔴 Stop
[1 sentence verdict]

Next: Phase [N+1] — [Name]
```

---

_See also: `docs/prompts/ORCHESTRATOR.md` · `docs/IMPLEMENTATION_CONTRACT.md` · `docs/DEVELOPMENT_METHOD.md`_
