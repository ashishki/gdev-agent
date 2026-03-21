# Session Management: Token Efficiency and Continuity

_Owner: Architecture · Updated: 2026-03-21_

This document describes how to manage Claude Code sessions efficiently to maximize output per token budget and how to recover when a session ends before a task is complete.

---

## Why This Matters

Claude Code sessions have a context window limit. A typical development session (reading files, running tests, writing code, reviewing) consumes 50k–200k tokens. Long sessions — especially with deep review agents, large diffs, or many file reads — can exhaust the limit mid-task.

There are two strategies: (1) **reduce consumption** so limits are hit less often, and (2) **auto-resume** when a session does end.

---

## Strategy 1: Token Efficiency (Primary)

### 1.1 Use Subagents for Isolated Work

Every review agent, codex exec call, and deep analysis runs in its own context window. The orchestrating session only sees the summary output — not the full agent transcript.

**Pattern:**
```
Orchestrator (small context)
  → Subagent: META review   (own context)
  → Subagent: ARCH review   (own context)
  → Subagent: CODE review   (own context)
```

This is the single most effective technique. Each subagent can consume its full context independently without growing the orchestrator's window.

**Rule:** Any task with > 5 file reads or > 2k lines of output should be a subagent.

### 1.2 Phase Checkpoints in CODEX_PROMPT.md

`docs/CODEX_PROMPT.md` is the session handoff document. It must always reflect:
- Current baseline (test count)
- Next task
- All open findings
- Completed task list

When a session ends, the next session starts by reading CODEX_PROMPT.md and picks up exactly where the previous left off — with zero context overhead.

**Discipline:** Update CODEX_PROMPT.md before committing at every phase boundary.

### 1.3 Read Selectively

Before reading a file, ask: "Do I need this to complete the current step?" Common wastes:
- Reading test files to understand production code (read production code only)
- Reading all files in a module when you need one function (use Grep first)
- Re-reading files already summarized in memory or CODEX_PROMPT

**Pattern:** Grep → read only the relevant lines (offset/limit) → edit.

### 1.4 Use `/compact` Before Large Tasks

The `/compact` command compresses prior conversation context before starting a memory-intensive task (deep review, large refactor). Run it:
- Before launching multiple review agents
- After a long test debugging session
- When starting a new phase

### 1.5 Parallel Agents for Independent Work

When two tasks have no dependencies, run them as parallel subagents. The orchestrator pays only for the final summaries, not the intermediate work.

**Example:** META review and ARCH review can run in parallel — they read the same files independently.

### 1.6 Keep Codex Prompts Precise

A vague codex prompt causes the agent to read more files "just in case" and produce longer responses. Each codex prompt should specify:
- Exact files to read (no more)
- Exact files to modify
- Expected return format (IMPLEMENTATION_RESULT: DONE | BLOCKED)

See `CODEX_PROMPT.md` for the current prompt template.

---

## Strategy 2: Auto-Resume on Limit (Option — activate if Strategy 1 insufficient)

### When to Use

Activate this strategy if:
- Multiple sessions per day hit the token limit before completing a phase
- Tasks regularly exceed 4 hours of continuous agent work
- Deep review cycles consistently exhaust the context

### Mechanism

**Step 1 — Checkpoint on limit:**

Claude Code has a `Stop` hook in settings. Configure it to write a checkpoint:

```json
// .claude/settings.json
{
  "hooks": {
    "Stop": [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "echo \"$(date -u +%Y-%m-%dT%H:%M:%SZ) SESSION_ENDED\" >> /tmp/gdev_session_log.txt"
      }]
    }]
  }
}
```

**Step 2 — Task state in PAUSE_STATE.md:**

Before the session ends (or proactively at each phase step), write:

```markdown
# PAUSE_STATE
Last completed: FIX-I commit 3/6
Next action: commit eval/runner.py changes
Baseline: 206 passing
Resume command: git status && pytest tests/ -q
```

**Step 3 — Resume trigger:**

Claude Code can be resumed manually by running:
```bash
claude "Read docs/PAUSE_STATE.md and docs/CODEX_PROMPT.md, then continue where the last session left off"
```

Or via a GitHub Actions scheduled job (runs every 6 hours):
```yaml
# .github/workflows/resume.yml
on:
  schedule:
    - cron: '0 */6 * * *'
jobs:
  check-and-resume:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Check for pause state
        run: |
          if [ -f docs/PAUSE_STATE.md ]; then
            echo "Pause state found — manual resume needed"
            # Notify via webhook or create GitHub Issue
          fi
```

### Limitation

Auto-resume via scheduled jobs requires Claude Code CLI access from CI, which requires API key configuration and approval. The scheduled approach is best for non-interactive batch tasks (tests, lint, doc generation) rather than interactive development.

---

## Summary

| Strategy | Effectiveness | Complexity | When |
|----------|--------------|------------|------|
| Subagents for isolation | Very high | Low (already standard) | Always |
| Phase checkpoints | High | Low (already standard) | Always |
| Selective file reading | Medium | Low | Always |
| `/compact` before large tasks | Medium | Very low | Before deep review/refactor |
| Parallel agents | High | Medium | Multi-part reviews |
| Auto-resume | High | High | Only if primary strategy insufficient |

**Default:** Use Strategy 1 techniques for every session. Revisit Strategy 2 if two or more sessions per week end before completing a phase.
