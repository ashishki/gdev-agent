# AI Engineering Framework

_v1.0 · gdev-agent_

## Agent Roles

| Agent | Prompt | Produces | Context (minimum) |
|-------|--------|----------|-------------------|
| **Codex** (implementer) | `CODEX_PROMPT.md` | code, tests | CODEX_PROMPT + tasks.md + task files |
| **META** (review entry) | `audit/PROMPT_0_META.md` | META_ANALYSIS.md | tasks.md + CODEX_PROMPT + REVIEW_REPORT |
| **ARCH** (drift check) | `audit/PROMPT_1_ARCH.md` | ARCH_REPORT.md | META_ANALYSIS + ARCHITECTURE + adr/ |
| **CODE** (code review) | `audit/PROMPT_2_CODE.md` | findings → step 3 | META_ANALYSIS + dev-standards + scope files |
| **CONSOLIDATED** (final) | `audit/PROMPT_3_CONSOLIDATED.md` | REVIEW_REPORT + patches | all step 0–2 outputs + tasks + CODEX_PROMPT |

**Load only what the role needs. Extra context degrades accuracy and increases cost.**

## Immutable Rules (require ADR to change)

1. All SQL parameterized — `text()` with named params, no string interpolation
2. Every DB call preceded by `SET LOCAL app.current_tenant_id` via `get_db_session()`
3. Redis in `async def` only via `redis.asyncio`
4. Every new route handler uses `require_role()`
5. No PII (user_id, email, raw text) in logs / span attrs / metrics — SHA-256 hashes only
6. `git grep -rn "sk-ant\|lin_api_\|AKIA\|Bearer " app/` must return empty

## Finding Lifecycle

```
Open → In Progress → Mitigated → Closed (requires code verification in PROMPT_3)
```

| Severity | Meaning | Blocks |
|----------|---------|--------|
| P0 | Release blocker / security / data loss | Phase gate |
| P1 | Correctness or reliability issue | Must have task in tasks.md |
| P2 | Important, non-blocking | Carries forward |
| P3 | Improvement / tech debt | Carries forward |

**Self-closing is forbidden.** A finding is Closed only when PROMPT_3 verifies the fix in code + a test exists.

## Dev Cycle

```
Codex implements T## → run audit pipeline (PROMPT_0→1→2→3) → REVIEW_REPORT.md
  └─ P0 found? → fix first, re-review
  └─ No P0? → Codex implements next task
```

## Document Versioning

| Document | Policy |
|----------|--------|
| `CODEX_PROMPT.md` | vX.Y; bump on contract change |
| `audit/REVIEW_REPORT.md` | Overwritten each cycle; previous → `archive/PHASE{N}_REVIEW.md` |
| `ARCHITECTURE.md` | vX.Y; update on structural change |
| `adr/` | Append-only; existing ADRs not edited |
| `archive/` | Write-only; nothing deleted |
