# Eval Baseline Report

Date: 2026-06-11

This report records the current local, deterministic eval baseline for the committed synthetic
dataset. It is local evidence for eval instrumentation and regression visibility, not a claim
of production model quality.

## Command

```bash
python -c "from pathlib import Path; from eval.runner import run_eval; print(run_eval(Path('eval/cases.jsonl')))"
```

The committed `eval/results/last_run.json` was generated with deterministic demo-mode behavior.
The direct runner falls back to demo mode when live mode is configured without an Anthropic API key.

For cross-project interpretation, read this report with
[docs/EVAL_SCOPE_RECONCILIATION.md](EVAL_SCOPE_RECONCILIATION.md). The 180-case
internal eval is a broad smoke/gap-discovery surface. The separate Eval Ground
Truth Lab 55-case baseline is a curated live local integration/conformance eval
over the configured `/webhook` adapter.

## Environment Assumptions

- Dataset: `eval/cases.jsonl`
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
| `classification_accuracy` | 0.2222 | Not gated yet | Observe | Demo-mode classifier only covers part of the expanded taxonomy. |
| `guard_block_rate` | 1.0000 | `>= 1.0000` | Pass | Known prompt-injection cases are blocked. |
| `risk_routing_recall` | 0.4259 | `>= 0.4000` | Pass | Baseline-compatible smoke threshold; higher target quality remains a known gap. |
| `unsafe_auto_approval_rate` | 0.5741 | `<= 0.6000` | Pass | Baseline-compatible smoke threshold; this still exposes routing work before quality claims. |
| `invalid_structured_output_rate` | 0.0000 | `<= 0.0000` | Pass | Current demo responses satisfy required structured fields. |
| `human_escalation_rate` | 0.2833 | Not gated yet | Observe | Useful for over- or under-escalation review. |
| `cost_usd_per_case` | 0.0000 | Not gated yet | Observe | Demo mode has no paid model cost. |
| `latency_ms_per_case` | 4.0560 | Not gated yet | Observe | Local timing signal only; varies by workstation. |

Additional counts:

- `total_cases`: 180
- `scored_cases`: 162
- `correct_classifications`: 36
- `expected_guard_blocks`: 18
- `unsafe_auto_approvals`: 93
- `invalid_structured_outputs`: 0
- `human_escalations`: 51

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
