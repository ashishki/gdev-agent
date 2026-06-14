# AI Systems Reliability Stack

This repository is one layer in a three-project local evidence stack for
reliable AI/agent systems.

## System Map

| Layer | Repository | Role | Current evidence |
| --- | --- | --- | --- |
| Governed workflow | `gdev-agent` | Multi-tenant support-triage workflow with webhook intake, guardrails, approval, audit, cost, and observability controls. | 285 tests, local Compose demo, 180-case internal smoke eval, load and isolation evidence. |
| Quality layer | `Eval-Ground-Truth-Lab` | Deterministic regression evaluation framework for structured output, routing, unsafe auto-approval, cost, latency, and adapter behavior. | 55-case live local gdev-agent baseline with zero adapter errors and zero validator failures. |
| Runtime layer | `Agent-Runtime-Grid` | Queue-backed runtime for running many AI/agent jobs with retries, timeouts, idempotent finalization, artifacts, metrics, and cost controls. | 100-job smoke, 500-job reliability proof, failure-injection reports, and cross-project artifact proof. |

## How They Connect

The simplest live local path is:

```text
Eval Ground Truth Lab
  -> configured HTTP adapter
  -> gdev-agent /webhook
  -> deterministic validators
  -> baseline report and run artifact
```

The Runtime Grid path is currently an artifact-linked runtime proof:

```text
Agent Runtime Grid
  -> selected Eval Lab / gdev case jobs
  -> Redis Streams workers
  -> Postgres lifecycle state
  -> runtime artifacts and reliability report
  -> links back to Eval Lab and gdev-agent evidence
```

That Runtime Grid mode does not call live `gdev-agent` over HTTP by default. A
future `full-stack-live-local` mode would run Grid workers that trigger Eval Lab
or the gdev HTTP adapter end to end.

## What An Agent Means Here

An agent is a bounded job type, not an open-ended autonomous persona. It has:

- input schema
- output schema
- allowed tools or side effects
- model/provider policy
- budget and timeout
- guardrail and approval rules
- eval cases and validators

In this stack:

- `gdev-agent` is the first real governed workflow under test.
- Eval Lab checks whether that workflow still behaves correctly.
- Runtime Grid runs many agent/eval jobs reliably and records runtime evidence.

## Provider Strategy

Default portfolio and CI mode should stay deterministic:

| Mode | Provider | Use |
| --- | --- | --- |
| `demo` / `stub` | deterministic fixtures | tests, CI, load/reliability proofs, zero-cost demos |
| `live` in `gdev-agent` | Anthropic Claude | implemented live support-triage provider path |
| optional judge in Eval Lab | OpenAI provider contract | bounded, budget-gated, non-authoritative judging |
| future runtime live jobs | model router over Anthropic/OpenAI/Gemini/Mistral/local | planned only after explicit budget, egress, and eval gates |
| future local mode | Ollama or vLLM | offline/dev/privacy/inference-infra demonstrations |

The important boundary is that runtime control decisions stay deterministic.
Providers may supply task intelligence, but they do not own scheduling, budget,
terminal state, tenant isolation, approval policy, or eval pass/fail authority.

## What Is Not Claimed

This stack is v1 local evidence, not production adoption evidence. It does not
claim external users, hosted SaaS operations, production SLOs, exactly-once
execution, or a general autonomous swarm.

