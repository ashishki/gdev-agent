# gdev-agent Workflow

_External overview of the AI-assisted development workflow used in this repository._
_For the full operating procedure, prompts, triggers, and state rules, see `docs/DEVELOPMENT_METHOD.md`._

---

## Purpose

gdev-agent is built with a structured AI development loop rather than ad hoc prompting.
The workflow is designed to make autonomous implementation inspectable, test-driven, and
reviewable by humans evaluating engineering maturity.

Three design choices define the process:

1. A human sets scope, priorities, and acceptance criteria.
2. The implementation agent writes code and tests, but does not self-certify.
3. Separate review agents evaluate the result before work is treated as complete.

This separation keeps task execution fast while preserving an explicit quality gate.

---

## Development Loop

```text
Human defines tasks and acceptance criteria
                    |
                    v
      Orchestrator reads project state from docs
                    |
     +--------------+---------------+
     |                              |
     v                              v
Fixes already open?           New task ready?
     |                              |
     v                              v
Codex implements fix         Codex implements task
     |                              |
     +--------------+---------------+
                    |
                    v
            Tests and validation
                    |
                    v
         Review tier selected by risk
          /                         \
         v                           v
 Light review                  Deep review
 (single reviewer)      (META -> ARCH -> CODE -> CONSOLIDATED)
         |                           |
         v                           v
   Findings? yes ----------------> Codex fixes
         |                           |
         no                          +------+
         |                                  |
         +-------------------<--------------+
                    |
                    v
       Archive phase outputs when required
                    |
                    v
                Next loop
```

The loop is stateless at the session level. The orchestrator re-reads task and handoff files
each run, which allows work to resume cleanly after interruptions or rate limits.

---

## Agent Roles

| Role | Primary responsibility | Typical output |
|---|---|---|
| **Human architect** | Defines tasks, acceptance criteria, priorities, and architectural decisions | `docs/tasks.md`, ADRs, stop-ship decisions |
| **Orchestrator** | Reads state, decides the next action, routes work to the right agent, updates workflow state | Loop control and state transitions |
| **Codex implementer** | Writes code, tests, and targeted fixes inside the repo | Code changes, tests, document updates |
| **Strategy reviewer** | Checks phase-level direction and whether the next slice of work still matches goals | `STRATEGY_NOTE.md` |
| **META reviewer** | Establishes review scope and risk framing for deep review | `META_ANALYSIS.md` |
| **Architecture reviewer** | Looks for drift against architecture docs and design decisions | `ARCH_REPORT.md` |
| **Code reviewer** | Performs file-level security, correctness, and testability review | Findings list |
| **Consolidation reviewer** | Merges deep-review outputs into a single decision and follow-up queue | `REVIEW_REPORT.md` |

The key control is role separation: the agent that writes the change is not the agent that
judges whether it is acceptable.

---

## Tool Split

The workflow intentionally separates implementation tooling from review tooling.

| Work type | Primary tool mode | Reason |
|---|---|---|
| Code and test changes | Codex in workspace-write mode | Needs direct repository edits, validation, and minimal diffs |
| Review and analysis | General-purpose review agents | Fresh context is better for architecture and defect detection |

This split reduces the risk of an agent rationalizing its own work. Build sessions optimize for
execution speed and repository correctness; review sessions optimize for independent judgment.

---

## Two-Tier Review System

| Tier | When used | Goal | Output |
|---|---|---|---|
| **Light review** | Routine task completion inside a phase | Fast contract, security, and implementation sanity check | Pass/fail plus issue list |
| **Deep review** | Phase boundaries, security-critical changes, or elevated risk | Broader architecture, security, and process audit | Consolidated report and fix queue |

### Light review

Light review is the default gate after normal implementation tasks. It is intentionally low-cost
and catches common failures quickly, such as contract violations, obvious security mistakes,
auth gaps, or missing tests.

### Deep review

Deep review is sequential and heavier-weight:

```text
META -> ARCH -> CODE -> CONSOLIDATED
```

Each stage narrows ambiguity for the next one. The result is not only a bug list, but also a
recorded phase-level quality decision and, when needed, a prioritized fix queue.

---

## Phase Cadence

The project is managed in phases, each containing a bounded set of tasks. The cadence is:

1. Complete tasks within the current phase.
2. Run light review after normal task completion.
3. At the phase boundary, run strategy review and deep review.
4. Archive the review output and update state documents.
5. Start the next phase with an updated handoff.

This cadence balances throughput and control. Most tasks move quickly through the loop, while
phase boundaries create deliberate checkpoints for broader architectural assessment.

---

## Why This Signals Workflow Maturity

For external evaluators, the important point is not that AI is used, but how it is constrained.
This workflow makes maturity visible through:

- Explicit acceptance criteria before implementation starts
- Separate implementer and reviewer roles
- A documented escalation from light review to deep review
- Persistent written state instead of hidden chat context
- Phase-based checkpoints with archived review artifacts

Those controls make the development process auditable, resumable, and easier to reason about than
an unstructured "prompt until it works" model.

---

## Further Detail

This document is intentionally brief and standalone. For the full operational specification,
including prompts, state files, review triggers, and finding lifecycle rules, see
`docs/DEVELOPMENT_METHOD.md`.
