# Eval Scope Reconciliation

`gdev-agent` now appears in five different eval/runtime surfaces. They intentionally
answer different questions.

## The Five Evidence Scopes

| Scope | Location | Cases | Question answered | Current interpretation |
| --- | --- | ---: | --- | --- |
| Internal gdev-agent smoke eval | `eval/cases.jsonl`, `docs/EVAL_REPORT.md` | 180 | Does the local demo-mode workflow expose broad taxonomy, guard, routing, and unsafe-auto-approval regressions? | Broad smoke signal. It intentionally exposes known demo-policy quality gaps. |
| Eval Lab integration baseline | `Eval-Ground-Truth-Lab/datasets/gdev_agent/triage_v1.jsonl`, `Eval-Ground-Truth-Lab/reports/gdev-agent/baseline_report.md` | 55 | Does Eval Lab's configured HTTP adapter reach a live local gdev-agent and validate the agreed triage contract? | Passing integration/conformance baseline: 55 cases, zero adapter errors, zero validator failures. |
| Eval Lab challenge diagnostic | [Eval Lab v0.2.0 canonical challenge evidence](https://github.com/ashishki/Eval-Ground-Truth-Lab/tree/main/docs/evidence/releases/v0.2.0/gdev-agent-challenge) | 100 | Where do ambiguous, policy-stress, malformed, and provider-failure cases expose gaps in a fixed candidate? | Canonical local run against exact gdev-agent revision `0e4c5f0fd50382bbf12ffd35cfca4632384fb0cc`: 90 HTTP candidate calls plus 10 labeled harness fault injections. Gate **FAIL**. |
| Runtime Grid artifact proof | `Agent-Runtime-Grid` `proof full-stack` | 20 default | Can selected Eval Lab/gdev evidence be run as queue-backed jobs with runtime artifacts, lifecycle state, and report cross-links? | Default runtime reliability proof over ready artifacts, not a live HTTP gdev-agent quality eval. |
| Runtime Grid live-local proof | `Agent-Runtime-Grid` `proof full-stack-live-local` | operator-selected; 20 in latest snapshot | Can Grid workers call a local gdev-agent HTTP endpoint while preserving queue lifecycle, sanitized artifacts, and report links? | Optional local HTTP proof. The 2026-06-15 committed snapshot completed 20/20 queued jobs against local demo-mode gdev-agent, but it does not replace Eval Lab's quality report or claim production traffic. |

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

Likewise, the 100 challenge cases are not a `100/100` result. Eval Lab executed
the canonical run against the fixed revision above and published the failure.
The reconciled pass rate was `0.32`; 68 cases were unexpected failures, including
58 blocking failures. The 10 deterministic provider-fault cases matched their
expected failures, but they are harness evidence rather than observed candidate
outages. The full artifact remains the authority for the case-level results.

## Canonical Challenge Result

The 2026-07-13 run used a clean local Compose/Redis state and the image digest
`sha256:7dc9fef2ec6fe25745405546ec69f6a6f64c1bfa9f052dc54abfd65498a6f6da`.
Eval Lab applied request namespace
`gdev-eval-v1-5c65a837141710c3f31f9978823394bd6d51feb3889524dd1ca67bbcf27c4222`
to both `request_id` and `message_id`, preventing a prior candidate/run from
satisfying Redis dedup for this run.

| Signal | Observed | Interpretation |
| --- | ---: | --- |
| Reconciled pass rate | `0.32` | Challenge gate failed; this is not a quality pass. |
| Classification accuracy | `0.244444` | Failed the `>= 0.70` challenge threshold. |
| Expected-failure match | `1.0` | All 10 deterministic provider-fault injections matched; not evidence of real provider outages. |
| Unexpected / blocking failures | `68` / `58` | Both failure-count gates failed. |
| Human review observed / escalation recall | `46` / `0.46` | Both human-routing gates failed. |
| Unsafe auto-approval / invalid output / cost per case | `0` / `0` / `$0` | These individual gates passed and do not override the overall failure. |
| Local p95 latency | `890.379885 ms` | Passed the challenge latency bound; not a production SLO. |

The verified evidence package is content-addressed as
`sha256:656face21f27b496d4d3e8bb0b588824f5737d122c1275c710f3e5b15ff94b4b`.
Its failed thresholds are blocking-failure maximum, classification-accuracy
minimum, human-review-count minimum, human-escalation-recall minimum, and
unexpected-failure maximum. Labels and thresholds were not relaxed to turn the
run green.

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
- Use the published case-level failures to improve general policy behavior;
  do not copy challenge wording into rules or weaken labels/thresholds to make
  the frozen public set pass.
- Re-run each candidate with a distinct deterministic request namespace and a
  clean service state, then publish failures as well as passes.
- Keep Runtime Grid `proof full-stack` as the reproducible artifact-linked
  proof, and use `proof full-stack-live-local` only as explicit local HTTP
  evidence when the operator has a local gdev-agent stack running.

## Operator Shortcut

Use the Eval Lab 55-case report to inspect integration correctness. Use the
internal 180-case report to inspect known quality gaps and regression visibility.
Use the [canonical 100-case challenge evidence](https://github.com/ashishki/Eval-Ground-Truth-Lab/tree/main/docs/evidence/releases/v0.2.0/gdev-agent-challenge)
to inspect the stricter gate failure and its case-level diagnostic coverage.
Use Runtime Grid artifact evidence to inspect batch execution reliability, and
use Runtime Grid live-local evidence only when you want to inspect queued local
HTTP execution against gdev-agent.
