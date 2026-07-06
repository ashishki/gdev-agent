# gdev-agent Agent Operating Rules

Purpose: keep coding and ops agents bounded when they work on this repository.
This repo is a governed support-triage workflow, not an autonomous agent swarm.

## Repository Rules

- Read `README.md`, `docs/ARCHITECTURE.md`, `docs/EVALUATION.md`, and
  `docs/HARNESS_CARD.md` before changing agent behavior.
- Treat `app/agent.py`, `app/llm_client.py`, guards, approval flow, tenant
  isolation, eval runner, and cost ledger as harness-critical code.
- Do not bypass input guard, output guard, approval gate, tenant boundary,
  budget checks, or eval thresholds to make a demo pass.
- Do not add live external side effects unless a human explicitly approves the
  integration boundary and rollback path.
- Keep committed eval data synthetic. Never add real tickets, customer data,
  API keys, tokens, emails, phone numbers, or production tenant identifiers.

## No Silent Workaround Policy

Ask the user instead of inventing a workaround when:

- a required secret, provider key, tenant credential, or webhook signature is
  missing;
- a migration, Redis/Postgres dependency, or eval gate fails for unclear
  reasons;
- a requested change would weaken approval, isolation, guardrail, or audit
  behavior;
- the available dataset cannot prove the claim being made;
- live LLM behavior differs from deterministic demo behavior.

## Permission Classes

| Class | Allowed Without Asking | Ask First | Blocked |
| --- | --- | --- | --- |
| Docs/eval fixtures | Add bounded docs, synthetic cases, and tests | Change public claims or baselines | Add real customer data |
| Local tests | Run pytest, ruff, eval gate, dry-run scripts | Start full Docker stack if it may affect local state | Skip failing safety tests silently |
| Code changes | Fix scoped bugs with tests | Change guardrails, approval, tenant isolation, budgets, or model routing | Remove human approval for risky actions |
| External systems | None by default | Live LLM, Telegram, Linear, Sheets, n8n, or webhooks | Store secrets in repo or logs |
| Data access | Synthetic fixtures and local test DB | Inspect non-synthetic local data | Exfiltrate tenant or production data |

## Required Review For Harness Changes

Any change to the agent harness must update or explicitly confirm:

- `docs/HARNESS_CARD.md`
- `docs/TRACE_SCHEMA.md`
- `docs/EVALUATION.md`
- `eval/cases.jsonl` or `eval/harness_regression.jsonl`
- relevant tests under `tests/`

If a change affects model prompts, tools, memory, retries, permissions, trace
shape, or human handoff, it is a harness change even when the code diff is small.
