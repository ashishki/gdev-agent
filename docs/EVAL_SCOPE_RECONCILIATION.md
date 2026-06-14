# Eval Scope Reconciliation

`gdev-agent` now appears in three different eval surfaces. They intentionally
answer different questions.

## The Three Eval Scopes

| Scope | Location | Cases | Question answered | Current interpretation |
| --- | --- | ---: | --- | --- |
| Internal gdev-agent smoke eval | `eval/cases.jsonl`, `docs/EVAL_REPORT.md` | 180 | Does the local demo-mode workflow expose broad taxonomy, guard, routing, and unsafe-auto-approval regressions? | Broad smoke signal. It intentionally exposes known demo-policy quality gaps. |
| Eval Lab integration baseline | `Eval-Ground-Truth-Lab/datasets/gdev_agent/triage_v1.jsonl`, `reports/gdev-agent/baseline_report.md` | 55 | Does Eval Lab's configured HTTP adapter reach a live local gdev-agent and validate the agreed triage contract? | Passing integration/conformance baseline: 55 cases, zero adapter errors, zero validator failures. |
| Runtime Grid artifact proof | `Agent-Runtime-Grid` `proof full-stack` | 20 default | Can selected Eval Lab/gdev evidence be run as queue-backed jobs with runtime artifacts, lifecycle state, and report cross-links? | Default runtime reliability proof over ready artifacts, not a live HTTP gdev-agent quality eval. |
| Runtime Grid live-local proof | `Agent-Runtime-Grid` `proof full-stack-live-local` | operator-selected | Can Grid workers call a local gdev-agent HTTP endpoint while preserving queue lifecycle, sanitized artifacts, and report links? | Optional local HTTP proof. It exercises runtime execution plus gdev HTTP transport, but it does not replace Eval Lab's quality report or claim production traffic. |

## Why The Metrics Differ

The internal 180-case report and the Eval Lab 55-case baseline are not measuring
the same thing.

The 180-case internal eval is a broad smoke taxonomy. It includes a wider spread
of billing, account, bug, moderation, legal, low-confidence, injection, unsafe
URL/output, duplicate webhook, and tenant-boundary cases. The current committed
metrics are intentionally labelled as deterministic demo-mode smoke evidence,
not production model quality.

The 55-case Eval Lab baseline is a curated integration/conformance eval over the
live local `/webhook` adapter path. It verifies that the agreed adapter contract,
normalizer, routing expectations, guard behavior, unsafe-auto-approval checks,
and cost telemetry all line up for that dataset.

So `55/55` in Eval Lab does not erase weak routing metrics in the broader
internal report. It means the integration contract is passing for the current
conformance set.

## Smoke Gates vs Quality Targets

| Metric | In internal 180-case eval | In Eval Lab 55-case baseline |
| --- | --- | --- |
| `guard_block_rate` | Smoke gate; should stay at `1.0000` for known injection cases. | Per-case guard behavior must match expected values. |
| `risk_routing_recall` | Smoke gate with baseline-compatible threshold. Low values expose demo-policy routing work. | Conformance target; expected-human routing must pass for every case. |
| `unsafe_auto_approval_rate` | Smoke gate with a loose threshold so CI catches regressions without claiming quality. | Must be `0.000` for the conformance baseline. |
| `classification_accuracy` | Observed quality target, not gated yet. | Conformance target for the 55-case dataset. |
| `cost_usd_per_case` | Demo-mode cost signal, currently `0.0000`. | Adapter contract requires deterministic cost telemetry, currently `0.0000`. |

## What To Improve Next

- Keep the 180-case internal eval as a broad smoke and gap-discovery surface.
- Add stricter quality gates only when the demo/live policy is improved across
  the broad taxonomy.
- Add a harder Eval Lab challenge set with ambiguous, expected-review,
  expected-failure, malformed, and policy-stress cases.
- Keep Runtime Grid `proof full-stack` as the reproducible artifact-linked
  proof, and use `proof full-stack-live-local` only as explicit local HTTP
  evidence when the operator has a local gdev-agent stack running.

## Reviewer Shortcut

Use the Eval Lab 55-case report to inspect integration correctness. Use the
internal 180-case report to inspect known quality gaps and regression visibility.
Use Runtime Grid artifact evidence to inspect batch execution reliability, and
use Runtime Grid live-local evidence only when you want to inspect queued local
HTTP execution against gdev-agent.
