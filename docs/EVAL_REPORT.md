# Eval Baseline Report

Date: 2026-07-13

This report records the current local, deterministic eval baseline for the committed synthetic
dataset. It is local evidence for eval instrumentation and regression visibility, not a claim
of production model quality.

## Command

```bash
PYTHONDONTWRITEBYTECODE=1 LLM_MODE=demo python -m eval.runner --gate
```

The committed `eval/results/last_run.json` was generated with deterministic demo-mode behavior.
The direct runner falls back to demo mode when live mode is configured without an Anthropic API key.

For cross-project interpretation, read this report with
[docs/EVAL_SCOPE_RECONCILIATION.md](EVAL_SCOPE_RECONCILIATION.md). The 180-case
internal eval is a broad smoke/gap-discovery surface. The separate Eval Ground
Truth Lab 55-case baseline is a curated live local integration/conformance eval
over the configured `/webhook` adapter. Eval Lab also contains a separate
100-case diagnostic challenge with a canonical failed run against this exact
gdev-agent revision; see the reconciliation document before comparing counts or
interpreting the separate gates.

## Environment Assumptions

- Dataset: `eval/cases.jsonl`
- Dataset SHA-256: `8db471b52ea78f6bf9daa3993630f57083277660f31ced8e85790860e0b98400`
- Dataset size: 180 synthetic cases
- Taxonomy: billing, account access, bug report, moderation, legal/GDPR, low confidence,
  injection attempt, unsafe URL/output, duplicate webhook, tenant boundary
- Runtime: local Python virtualenv
- LLM mode: deterministic demo behavior for this baseline
- External services: no live LLM, customer data, or production tenant data required

## Baseline Metrics

Source: `eval/results/last_run.json`

| Metric | Current value | Threshold | Result | Interpretation |
| --- | ---: | --- | --- | --- |
| `classification_accuracy` | 0.1698 | Not gated yet | Observe | Demo-mode classifier only covers part of the expanded taxonomy. |
| `guard_block_rate` | 1.0000 | `>= 1.0000` | Pass | Known prompt-injection cases are blocked. |
| `risk_routing_recall` | 0.5370 | `>= 0.4000` | Pass | Baseline-compatible smoke threshold; higher target quality remains a known gap. |
| `unsafe_auto_approval_rate` | 0.4630 | `<= 0.6000` | Pass | Baseline-compatible smoke threshold; this still exposes routing work before quality claims. |
| `invalid_structured_output_rate` | 0.0000 | `<= 0.0000` | Pass | Current demo responses satisfy required structured fields. |
| `human_escalation_rate` | 0.3833 | Not gated yet | Observe | Useful for over- or under-escalation review. |
| `cost_usd_per_case` | 0.0000 | Not gated yet | Observe | Demo mode has no paid model cost. |
| `latency_ms_per_case` | 10.0600 | Not gated yet | Observe | Local timing signal only; varies by workstation. |

Additional counts:

- `total_cases`: 180
- `scored_cases`: 159
- `correct_classifications`: 27
- `guard_blocks`: 21
- `expected_guard_blocks`: 18
- `unsafe_auto_approvals`: 75
- `invalid_structured_outputs`: 0
- `human_escalations`: 69

The runner now derives allowed classification categories from
`app.schemas.Category` and treats runtime `blocked`/`guard_blocked` responses as
valid safety outcomes in both direct and persisted-job execution. No case labels
or thresholds were changed for this repair. The lower classification score and
the stronger routing counts above are the resulting observed baseline, not a
relabelled improvement claim.

## Thresholds

The current deterministic CI smoke threshold set is implemented in
`eval.runner.DEFAULT_EVAL_THRESHOLDS`:

| Metric | Comparator | Threshold |
| --- | --- | ---: |
| `risk_routing_recall` | `>=` | 0.40 |
| `unsafe_auto_approval_rate` | `<=` | 0.60 |
| `invalid_structured_output_rate` | `<=` | 0.00 |
| `guard_block_rate` | `>=` | 1.00 |

These thresholds are intentionally baseline-compatible so CI can catch regressions without claiming
the current demo stub is high-quality across the whole taxonomy. They are smoke thresholds, not
product quality targets.

## Relationship To Eval Lab Baseline

Eval Ground Truth Lab now has a separate 55-case gdev-agent integration baseline
that calls a live local `gdev-agent` through the HTTP adapter and records zero
adapter errors and zero deterministic validator failures. That result proves the
current adapter/conformance contract for the curated Eval Lab dataset.

Eval Lab's 100-case `challenge_v1.jsonl` is an executable diagnostic surface
with a manifest, threshold gate, and explicit deterministic fault injection for
the final provider-error slice. Its canonical local run fixed gdev-agent at
`0e4c5f0fd50382bbf12ffd35cfca4632384fb0cc`, executed 90 HTTP candidate cases,
and reconciled 10 deterministic fault injections. The gate **failed**: `0.32`
reconciled pass rate, `0.244444` classification accuracy, 68 unexpected failures,
58 blocking failures, 46 human-review outcomes, and `0.46` human-escalation
recall. The verified package is
[published by Eval Lab](https://github.com/ashishki/Eval-Ground-Truth-Lab/tree/main/docs/evidence/releases/v0.2.0/gdev-agent-challenge)
with content address
`sha256:656face21f27b496d4d3e8bb0b588824f5737d122c1275c710f3e5b15ff94b4b`.

It does not invalidate this internal 180-case report. This report remains the
broader local smoke taxonomy and intentionally keeps weak routing and
classification metrics visible until the demo/live policy improves across the
expanded dataset.

## Known Limits

- The dataset is synthetic and does not prove real customer support quality.
- The baseline uses deterministic demo behavior, not a paid live model evaluation.
- Routing metrics still expose gaps in demo-mode policy coverage across the expanded taxonomy.
- `latency_ms_per_case` is local workstation timing, not an SLO or production latency claim.
- The CI regression gate is active for smoke regressions; stricter quality gates remain future work.
- The 55-case Eval Lab baseline should be read as integration/conformance
  evidence, not as a replacement for this broader internal smoke surface.
