# Eval Baseline Report

Date: 2026-06-11

This report records the current local, deterministic eval baseline for the committed synthetic
dataset. It is portfolio evidence for eval instrumentation and regression visibility, not a claim
of production model quality.

## Command

```bash
python -c "from pathlib import Path; from eval.runner import run_eval; print(run_eval(Path('eval/cases.jsonl')))"
```

The committed `eval/results/last_run.json` was generated with deterministic demo-mode behavior.
The direct runner falls back to demo mode when live mode is configured without an Anthropic API key.

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
| `risk_routing_recall` | 0.4259 | `>= 0.9500` | Fail | Many synthetic high-risk taxonomy cases are still auto-executed by the demo stub. |
| `unsafe_auto_approval_rate` | 0.5741 | `<= 0.0000` | Fail | The metric exposes unsafe routing regressions before CI gating is enabled. |
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

The current deterministic threshold set is implemented in `eval.runner.DEFAULT_EVAL_THRESHOLDS`:

| Metric | Comparator | Threshold |
| --- | --- | ---: |
| `risk_routing_recall` | `>=` | 0.95 |
| `unsafe_auto_approval_rate` | `<=` | 0.00 |
| `invalid_structured_output_rate` | `<=` | 0.00 |
| `guard_block_rate` | `>=` | 1.00 |

These thresholds are intentionally stricter than the current demo baseline for routing. T10 will
wire these signals into CI; until then, the report should be read as a visible baseline plus known
gaps, not as a passing quality gate.

## Known Limits

- The dataset is synthetic and does not prove real customer support quality.
- The baseline uses deterministic demo behavior, not a paid live model evaluation.
- Routing metrics currently expose gaps in demo-mode policy coverage across the expanded taxonomy.
- `latency_ms_per_case` is local workstation timing, not an SLO or production latency claim.
- The CI regression gate is not active until T10.
