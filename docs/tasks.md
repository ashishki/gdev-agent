# gdev-agent Tasks

Status: portfolio-hardening-active
Last updated: 2026-06-12
Source: `GDEV_AGENT_PORTFOLIO_HARDENING_PLAN.md` provided by human.

This file is the active task graph for the AI-assisted development loop. The
goal is to harden `gdev-agent` as a high-trust hiring artifact: reliability,
evaluation discipline, tenant isolation, observability, deployment readiness,
and clear evidence paths.

This is not a product expansion plan.

## Hard Scope Boundaries

- Do not turn the project into a full SaaS product.
- Do not add a chat UI.
- Do not add open-ended multi-agent behavior.
- Do not claim production readiness without external deployment or users.
- Do not add features that distract from reliability, eval, governance, or
  evidence.
- Keep public claims specific, bounded, and backed by runnable proof.

## Status Legend

| Symbol | Meaning |
|---|---|
| `[ ]` | Not started |
| `[~]` | Implemented, pending review |
| `[x]` | Complete, implemented and reviewed |
| `[!]` | Blocked, needs human input |

## Validation Rules

- Code or test changes must run `ruff check app/ tests/` and `pytest tests/ -q`
  unless the task explicitly narrows validation.
- Documentation-only tasks do not need application tests, but must include a
  grep/link sanity check in the completion report.
- Security-critical tasks touching auth, middleware, RLS, tenant isolation, or
  secrets require deep review.
- Keep task diffs scoped to the listed files unless local code discovery shows a
  direct dependency.

---

## Phase 0 - Positioning And Evidence Map

Status: active
Business goal: make the strongest proof easy to find in 10-15 minutes.
Exit criteria: README links to architecture, tests, eval, load, demo, failure
modes, SLO/runbook, observability, and known limits with bounded status claims.

### [x] T01: README Positioning And Bounded Status

Owner: Codex
Priority: P1
Type: docs
Depends-On: none

Objective:
Reframe the public entrypoint around "multi-tenant LLM workflow reliability
system" and remove any implication that the local stack is a production SaaS.

Files to create/modify:
- `README.md`
- `docs/PROJECT_PLAN.md`

Acceptance Criteria:
1. README opening states the project as a governed, multi-tenant LLM workflow
   reliability system for game-studio support.
2. README and project plan clearly say the stack is pilot-grade/local and does
   not claim production SaaS readiness.
3. README has a compact evidence path linking to architecture, demo, eval,
   observability, load profile, tenant isolation/security, and known limits.
4. No new product feature scope is introduced.

Validation:
- `rg -n "reliability|pilot|production SaaS|evidence|known limits" README.md docs/PROJECT_PLAN.md`

### [x] T02: Evidence Index

Owner: Codex
Priority: P1
Type: docs
Depends-On: T01

Objective:
Create a single evidence index that maps each portfolio claim to a doc, test,
script, or report.

Files to create/modify:
- `docs/EVIDENCE_INDEX.md`
- `README.md`

Acceptance Criteria:
1. `docs/EVIDENCE_INDEX.md` links to architecture, eval, load profile/report,
   failure modes, tenant isolation, SLO/runbook, observability, demo, and CI.
2. Each evidence row names the claim, proof artifact, verification command or
   test file, and current gap if the proof is incomplete.
3. README links to the evidence index from the first-screen review path.

Validation:
- `rg -n "EVIDENCE_INDEX|Claim|Proof|Verification|Gap" README.md docs/EVIDENCE_INDEX.md`

### [x] T03: Fifteen-Minute Portfolio Review Guide

Owner: Codex
Priority: P1
Type: docs
Depends-On: T02

Objective:
Add a reviewer-oriented guide that shows how to inspect the repo quickly without
reading every internal process document.

Files to create/modify:
- `docs/PORTFOLIO_REVIEW_GUIDE.md`
- `README.md`

Acceptance Criteria:
1. Guide has a 5-minute path, 15-minute path, and technical deep-dive path.
2. Guide links to architecture, demo, eval, load, failure modes, tenant
   isolation, observability, and final known limits.
3. Guide avoids AI-development process noise unless it helps explain evidence
   quality.
4. README links to the guide near the top.

Validation:
- `rg -n "5-minute|15-minute|deep-dive|PORTFOLIO_REVIEW_GUIDE" README.md docs/PORTFOLIO_REVIEW_GUIDE.md`

---

## Phase 1 - Repeatable Demo Pack

Status: planned
Business goal: make the main workflow understandable without real API keys,
domain setup, or paid model calls.
Exit criteria: a fresh clone can run a deterministic demo that produces webhook
response, pending approval, approval decision, audit rows, metrics, and readable
output.

### [x] T04: Demo Fixture Inventory And Seed Contract

Owner: Codex
Priority: P1
Type: docs/tests
Depends-On: T03

Objective:
Document and test the synthetic tenants, secrets, users, and support cases used
by the local demo.

Files to create/modify:
- `docker/seed.sql`
- `scripts/seed_db.py`
- `docs/DEMO.md`
- `tests/test_cli.py`
- `tests/test_load_test_fixtures.py`

Acceptance Criteria:
1. Demo tenant slugs, tenant IDs, secrets, admin users, and approval secrets are
   documented in one table.
2. Seed data includes normal, risky, adversarial, low-confidence, and duplicate
   support-ticket examples or points to committed fixture files for them.
3. Tests fail if demo tenant credentials or fixture assumptions drift from docs.
4. No real secrets or production-like credentials are added.

Validation:
- `pytest tests/test_cli.py tests/test_load_test_fixtures.py -q`

### [x] T05: Deterministic Demo LLM Mode

Owner: Codex
Priority: P1
Type: code/tests/docs
Depends-On: T04

Objective:
Make the demo free and deterministic by routing demo-mode model calls through
stubbed responses while preserving the same service boundaries.

Files to create/modify:
- `app/config.py`
- `app/agent.py`
- `app/llm_client.py`
- `scripts/demo.py`
- `docs/DEMO.md`
- `tests/test_llm_client.py`
- `tests/test_agent.py`
- `tests/test_webhook_service.py`

Acceptance Criteria:
1. Demo mode can run without an external LLM API call.
2. Optional live LLM mode remains available and clearly requires an API key and
   budget cap.
3. Stubbed responses cover at least normal, risky, adversarial, and malformed
   output paths.
4. Tests prove demo mode uses deterministic fixtures and does not bypass input,
   policy, output, approval, audit, or cost boundaries.

Validation:
- `pytest tests/test_llm_client.py tests/test_agent.py tests/test_webhook_service.py -q`
- `ruff check app/ tests/`

### [x] T06: End-To-End Demo Command

Owner: Codex
Priority: P1
Type: code/tests/docs
Depends-On: T05

Objective:
Add a single command that runs the main workflow end to end and emits a concise
transcript suitable for a portfolio reviewer.

Files to create/modify:
- `Makefile`
- `scripts/demo.py`
- `scripts/demo.sh`
- `docs/DEMO.md`
- `tests/test_cli.py`

Acceptance Criteria:
1. `make demo` or equivalent documented command runs against the local stack in
   deterministic mode.
2. Demo output shows health, auth, signed webhook, pending approval, approval
   decision, audit lookup, and metrics check.
3. Demo exits non-zero with a clear error if the stack is unavailable or seed
   data is missing.
4. Documentation includes expected transcript and troubleshooting notes.

Validation:
- `pytest tests/test_cli.py -q`
- `bash scripts/demo.sh --help` or documented equivalent dry-run check

---

## Phase 2 - Evaluation Hardening

Status: complete
Business goal: prove quality with versioned datasets, deterministic validators,
baseline metrics, and regression gates.
Exit criteria: eval reports answer accuracy, guardrail, routing, structure,
latency, and cost questions with reproducible commands.

### [x] T07: Eval Dataset Taxonomy Expansion

Owner: Codex
Priority: P1
Type: data/tests/docs
Depends-On: T06

Objective:
Expand the eval corpus from a small seed set into an inspectable taxonomy of
150-300 synthetic cases.

Files to create/modify:
- `eval/cases.jsonl`
- `docs/EVALUATION.md`
- `tests/test_eval_runner.py`
- `tests/test_eval.py`

Acceptance Criteria:
1. Dataset includes billing, account access, bug report, moderation, legal/GDPR,
   low confidence, injection attempt, unsafe URL/output, duplicate webhook, and
   tenant boundary cases.
2. Every case includes stable IDs, category, risk expectation, expected routing,
   expected guard behavior, and tenant context where relevant.
3. Tests validate JSONL schema, taxonomy coverage, and minimum case count.
4. Cases are synthetic and contain no real customer data.

Validation:
- `pytest tests/test_eval_runner.py tests/test_eval.py -q`

### [x] T08: Eval Validators And Metrics

Owner: Codex
Priority: P1
Type: code/tests/docs
Depends-On: T07

Objective:
Add deterministic validators and metrics that make eval regressions visible
beyond a single aggregate score.

Files to create/modify:
- `eval/runner.py`
- `eval/results/last_run.json`
- `docs/EVALUATION.md`
- `tests/test_eval_runner.py`
- `tests/test_eval_service.py`

Acceptance Criteria:
1. Eval computes classification accuracy, risk-routing recall, unsafe
   auto-approval rate, invalid structured output rate, guard block rate,
   human-escalation rate, cost per case, and latency per case.
2. Structured output validators fail closed on missing or malformed required
   fields.
3. Metrics are serialized into eval result JSON with stable names.
4. Tests include at least one seeded unsafe regression that causes a failing
   metric.

Validation:
- `pytest tests/test_eval_runner.py tests/test_eval_service.py -q`
- `python -c "from pathlib import Path; from eval.runner import run_eval; print(run_eval(Path('eval/cases.jsonl')))"`

### [x] T09: Baseline Eval Report

Owner: Codex
Priority: P1
Type: docs/data
Depends-On: T08

Objective:
Publish the current eval baseline and thresholds in a reviewer-readable report.

Files to create/modify:
- `docs/EVAL_REPORT.md`
- `docs/EVIDENCE_INDEX.md`
- `README.md`
- `eval/results/last_run.json`

Acceptance Criteria:
1. Report includes command, environment assumptions, dataset size, metrics,
   thresholds, and interpretation.
2. Report clearly labels known limits and does not overclaim real-world model
   quality.
3. Evidence index and README link to the report.
4. Baseline result file matches the documented metric names.

Validation:
- `rg -n "EVAL_REPORT|classification_accuracy|unsafe_auto_approval|threshold|known limits" README.md docs/EVIDENCE_INDEX.md docs/EVAL_REPORT.md eval/results/last_run.json`

### [x] T10: CI Eval Regression Gate

Owner: Codex
Priority: P1
Type: ci/tests/docs
Depends-On: T09

Objective:
Fail CI when critical eval metrics regress below documented thresholds.

Files to create/modify:
- `.github/workflows/ci.yml`
- `eval/runner.py`
- `docs/EVALUATION.md`
- `docs/EVAL_REPORT.md`
- `tests/test_eval_runner.py`

Acceptance Criteria:
1. CI runs the lightweight eval gate against committed synthetic data.
2. Thresholds cover risk-routing recall, unsafe auto-approval rate, invalid
   structured output rate, and guard block rate.
3. A seeded unsafe regression test proves the gate fails when expected.
4. Docs explain how to run the gate locally.

Validation:
- `pytest tests/test_eval_runner.py -q`
- `python -m eval.runner --help` or documented eval gate command

---

## Phase 3 - Reliability And Failure-Mode Proof

Status: active
Business goal: prove predictable behavior under replay, dependency failure,
provider errors, guard failures, approval expiry, and budget/rate pressure.
Exit criteria: every major failure mode has a named expected behavior, test or
scenario, and runbook response.

### [x] T11: Failure Mode Taxonomy And Runbook

Owner: Codex
Priority: P1
Type: docs
Depends-On: T10

Objective:
Create the canonical failure-mode document and error taxonomy before expanding
scenario tests.

Files to create/modify:
- `docs/FAILURE_MODES.md`
- `docs/SLO_RUNBOOK.md`
- `docs/EVIDENCE_INDEX.md`
- `docs/observability.md`
- `docs/load-profile.md`

Acceptance Criteria:
1. Document covers duplicate webhook replay, Redis unavailable/degraded,
   Postgres unavailable/degraded, LLM timeout, malformed LLM output, output
   guard block, approval TTL expiry, cross-tenant approval attempt,
   rate-limit exceedance, and budget exceedance.
2. Each row names trigger, expected user-visible behavior, logs/metrics/traces,
   retry/idempotency behavior, and operator response.
3. Error taxonomy uses stable names that tests and logs can reference.
4. SLO/runbook notes define local portfolio targets for latency, error rate,
   approval queue behavior, guard blocks, and dependency failure response
   without claiming a production SLA.
5. Evidence index links the failure-mode and SLO/runbook documents.

Validation:
- `rg -n "duplicate webhook|Redis|Postgres|LLM timeout|approval TTL|budget exceedance|SLO|runbook|FAILURE_MODES" docs/FAILURE_MODES.md docs/SLO_RUNBOOK.md docs/EVIDENCE_INDEX.md`

### [x] T12: Replay And Guard Failure Tests

Owner: Codex
Priority: P1
Type: tests/docs
Depends-On: T11

Objective:
Back the replay and guard-related failure modes with tests.

Files to create/modify:
- `tests/test_dedup.py`
- `tests/test_guardrails_and_extraction.py`
- `tests/test_output_guard.py`
- `tests/test_webhook_service.py`
- `docs/FAILURE_MODES.md`

Acceptance Criteria:
1. Duplicate webhook replay returns a predictable idempotent response and does
   not double-create tickets, approvals, audit rows, or cost entries.
2. Malformed LLM output fails closed into safe escalation or error taxonomy.
3. Output guard blocks unsafe URLs/secrets and records the expected metric/log
   signal.
4. Failure-mode docs cite the exact test files.

Validation:
- `pytest tests/test_dedup.py tests/test_guardrails_and_extraction.py tests/test_output_guard.py tests/test_webhook_service.py -q`

### [ ] T13: Provider And Dependency Degradation Tests

Owner: Codex
Priority: P1
Type: tests/docs
Depends-On: T11

Objective:
Prove behavior when external dependencies are slow, unavailable, or return
errors.

Files to create/modify:
- `tests/test_llm_client.py`
- `tests/test_webhook_service.py`
- `tests/test_redis_approval_store.py`
- `tests/test_db.py`
- `tests/test_middleware.py`
- `docs/FAILURE_MODES.md`

Acceptance Criteria:
1. LLM timeout/provider error has deterministic retry or fail-closed behavior.
2. Redis unavailable/degraded behavior is covered for rate limit, dedup, and
   approval storage paths.
3. Postgres unavailable/degraded behavior is covered for request/audit paths.
4. Tests assert stable error taxonomy values and no unsafe auto-execution.

Validation:
- `pytest tests/test_llm_client.py tests/test_webhook_service.py tests/test_redis_approval_store.py tests/test_db.py tests/test_middleware.py -q`

### [ ] T14: Approval Rate Budget And Tenant-Boundary Failure Tests

Owner: Codex
Priority: P0
Type: tests/docs
Depends-On: T11

Objective:
Cover high-risk operational boundaries: approval TTL, cross-tenant approval,
rate-limit exceedance, and budget exceedance.

Files to create/modify:
- `tests/test_approval_flow.py`
- `tests/test_approval_service.py`
- `tests/test_cost_ledger.py`
- `tests/test_middleware.py`
- `tests/test_isolation.py`
- `docs/FAILURE_MODES.md`
- `docs/TENANT_ISOLATION.md`

Acceptance Criteria:
1. Approval TTL expiry blocks stale approvals and records expected audit state.
2. Cross-tenant approval attempts are rejected before execution.
3. Rate-limit exceedance returns bounded errors without model calls.
4. Budget exceedance blocks LLM spend and records cost/budget evidence.
5. Tests prove these paths cannot create unsafe auto-approved actions.

Validation:
- `pytest tests/test_approval_flow.py tests/test_approval_service.py tests/test_cost_ledger.py tests/test_middleware.py tests/test_isolation.py -q`
- Deep review required.

---

## Phase 4 - Load Profile And Observability Proof

Status: planned
Business goal: show measurable local behavior under realistic portfolio-scale
traffic and make debugging paths visible.
Exit criteria: load tests are reproducible locally and reports map metrics,
traces, and logs to user-visible workflow steps.

### [ ] T15: Load Test Harness Alignment

Owner: Codex
Priority: P1
Type: code/tests/docs
Depends-On: T14

Objective:
Align the existing Locust harness with the hardening scenarios and make it
safe to run in deterministic demo mode.

Files to create/modify:
- `load_tests/locustfile.py`
- `load_tests/scenarios/steady.py`
- `load_tests/scenarios/burst.py`
- `load_tests/fixtures/sample_messages.jsonl`
- `load_tests/check_kpis.py`
- `docs/load-profile.md`
- `tests/test_load_test_fixtures.py`

Acceptance Criteria:
1. Harness supports 1-tenant low load, 10-tenant mixed load, duplicate replay
   storm, risky-action heavy traffic, and provider-latency simulation.
2. Fixture validation prevents real PII or real secrets.
3. KPI checker reports p50/p95/p99 latency, error rate, pending approval rate,
   dedup hit rate, guard block rate, and estimated cost per request.
4. Docs include exact local commands.

Validation:
- `pytest tests/test_load_test_fixtures.py -q`
- `python load_tests/check_kpis.py --help` or documented dry-run equivalent

### [ ] T16: Load Test Report

Owner: Codex
Priority: P1
Type: docs/data
Depends-On: T15

Objective:
Publish a reproducible load-test report without overstating production capacity.

Files to create/modify:
- `docs/LOAD_TEST_REPORT.md`
- `docs/EVIDENCE_INDEX.md`
- `README.md`
- `load_tests/results/`

Acceptance Criteria:
1. Report includes commands, local environment, scenario configuration, results,
   known limits, and interpretation.
2. Report includes p50/p95/p99 latency, error rate, approval creation rate,
   cost estimate, Redis/Postgres notes, dedup hit rate, and guard block rate.
3. Report explicitly labels results as local deterministic/synthetic evidence.
4. README and evidence index link to the report.

Validation:
- `rg -n "LOAD_TEST_REPORT|p50|p95|p99|dedup|guard block|known limits" README.md docs/EVIDENCE_INDEX.md docs/LOAD_TEST_REPORT.md`

### [ ] T17: Observability Debugging Evidence

Owner: Codex
Priority: P1
Type: docs/assets/tests
Depends-On: T16

Objective:
Map metrics, traces, logs, and dashboards to the support workflow and failure
modes.

Files to create/modify:
- `docs/observability.md`
- `docker/grafana/provisioning/dashboards/gdev-agent.json`
- `docs/EVIDENCE_INDEX.md`
- `tests/test_observability.py`
- `tests/test_metrics.py`

Acceptance Criteria:
1. Observability docs list metric names and explain which workflow step each
   metric/debug signal answers.
2. Dashboard export or screenshots/JSON are committed for the main local
   workflow.
3. Tests assert important metric names and tenant-safe labels.
4. Failure-mode docs cross-link to relevant metrics/traces/logs.

Validation:
- `pytest tests/test_observability.py tests/test_metrics.py -q`
- `rg -n "gdev_requests_total|tenant_hash|trace|dashboard|observability" docs/observability.md docker/grafana/provisioning/dashboards/gdev-agent.json`

---

## Phase 5 - Tenant Isolation And Security Proof

Status: planned
Business goal: back every multi-tenancy claim with concrete docs, adversarial
examples, and tests.
Exit criteria: reviewer can find and run tenant-isolation proof from README.

### [ ] T18: Tenant Isolation Evidence Document

Owner: Codex
Priority: P0
Type: docs
Depends-On: T17

Objective:
Create the canonical tenant isolation and security boundary document.

Files to create/modify:
- `docs/TENANT_ISOLATION.md`
- `docs/data-map.md`
- `docs/EVIDENCE_INDEX.md`
- `README.md`

Acceptance Criteria:
1. Document explains RLS, tenant-scoped JWT, webhook signature boundaries,
   approval boundaries, tenant secret isolation, and cost ledger separation.
2. Document states what is protected and what is not protected.
3. Document links to exact tests and migrations that enforce isolation.
4. README and evidence index link to the proof.

Validation:
- `rg -n "TENANT_ISOLATION|RLS|tenant-scoped JWT|webhook signature|cost ledger|not protected" README.md docs/EVIDENCE_INDEX.md docs/TENANT_ISOLATION.md`
- Deep review required.

### [ ] T19: RLS JWT Secret And Cost Isolation Tests

Owner: Codex
Priority: P0
Type: tests/docs
Depends-On: T18

Objective:
Ensure the strongest tenant isolation claims have direct tests.

Files to create/modify:
- `tests/test_isolation.py`
- `tests/test_rbac.py`
- `tests/test_auth_service.py`
- `tests/test_secrets_store.py`
- `tests/test_cost_ledger.py`
- `docs/TENANT_ISOLATION.md`

Acceptance Criteria:
1. Tests cover RLS read/write isolation across tenants.
2. Tests cover tenant-scoped JWT enforcement on tenant read APIs.
3. Tests cover per-tenant secret isolation.
4. Tests cover tenant-separated cost ledger reads/writes.
5. Docs cite the test names.

Validation:
- `pytest tests/test_isolation.py tests/test_rbac.py tests/test_auth_service.py tests/test_secrets_store.py tests/test_cost_ledger.py -q`
- Deep review required.

### [ ] T20: Adversarial Tenant Boundary Scenarios

Owner: Codex
Priority: P0
Type: tests/docs
Depends-On: T19

Objective:
Add adversarial tenant-crossing examples that mirror reviewer concerns.

Files to create/modify:
- `tests/test_endpoints.py`
- `tests/test_approval_flow.py`
- `tests/test_middleware.py`
- `tests/test_webhook_service.py`
- `docs/TENANT_ISOLATION.md`
- `docs/FAILURE_MODES.md`

Acceptance Criteria:
1. Tenant A cannot read tenant B audit logs.
2. Tenant A cannot approve tenant B pending action.
3. Missing or invalid tenant slug is rejected predictably.
4. Invalid HMAC signature is rejected before model calls or side effects.
5. Failure-mode and tenant-isolation docs link to these scenarios.

Validation:
- `pytest tests/test_endpoints.py tests/test_approval_flow.py tests/test_middleware.py tests/test_webhook_service.py -q`
- Deep review required.

---

## Phase 6 - Deployment Readiness Without Overclaiming

Status: planned
Business goal: prove setup, migration, health, secrets, and recovery are
understood while keeping deployment claims honest.
Exit criteria: fresh-clone local setup is reliable and deployment docs state
known limits clearly.

### [ ] T21: Compose Migration And Health Hardening

Owner: Codex
Priority: P1
Type: code/tests/docs
Depends-On: T20

Objective:
Make local Docker Compose setup and migration checks easy to verify.

Files to create/modify:
- `docker-compose.yml`
- `scripts/cli.py`
- `docs/DEMO.md`
- `docs/PROJECT_PLAN.md`
- `tests/test_cli.py`
- `tests/test_migrations.py`

Acceptance Criteria:
1. Documented migration check command verifies current schema state.
2. Health/readiness/liveness behavior is explained for the local stack.
3. Compose services have clear dependency and health behavior.
4. Tests cover migration command behavior or documented smoke path.

Validation:
- `pytest tests/test_cli.py tests/test_migrations.py -q`
- `docker compose config >/tmp/gdev-compose-config.txt`

### [ ] T22: Secrets Backup Restore And Production-Like Config Notes

Owner: Codex
Priority: P1
Type: docs/config
Depends-On: T21

Objective:
Add deployment-readiness notes that are useful without pretending the project is
a production platform.

Files to create/modify:
- `.env.example`
- `docs/DEPLOYMENT_READINESS.md`
- `docs/EVIDENCE_INDEX.md`
- `README.md`

Acceptance Criteria:
1. Document includes secrets checklist, local production-like config example,
   backup/restore notes for Postgres and Redis state, and known limitations.
2. Required vs optional environment variables are clear.
3. Docs explicitly avoid claiming production readiness.
4. README and evidence index link to deployment readiness notes.

Validation:
- `rg -n "DEPLOYMENT_READINESS|secrets checklist|backup|restore|known limitations|production readiness" README.md docs/EVIDENCE_INDEX.md docs/DEPLOYMENT_READINESS.md .env.example`

---

## Phase 7 - Hiring Packaging

Status: planned
Business goal: package the evidence so hiring managers and technical
interviewers can review quickly and drill down when needed.
Exit criteria: one-page case study, architecture visual, demo artifact notes,
and measured resume bullets are available.

### [ ] T23: One-Page Case Study

Owner: Codex
Priority: P1
Type: docs
Depends-On: T22

Objective:
Create a concise case study that tells the engineering story through evidence.

Files to create/modify:
- `docs/CASE_STUDY.md`
- `docs/EVIDENCE_INDEX.md`
- `README.md`

Acceptance Criteria:
1. Case study covers problem, architecture, control boundaries, failure modes,
   eval results, load results, trade-offs, and what would change for production.
2. Claims link back to evidence artifacts instead of repeating unsupported
   marketing language.
3. README links to the case study in the reviewer path.

Validation:
- `rg -n "CASE_STUDY|problem|architecture|failure modes|eval results|load results|production" README.md docs/EVIDENCE_INDEX.md docs/CASE_STUDY.md`

### [ ] T24: Architecture Diagram Asset

Owner: Codex
Priority: P2
Type: docs/assets
Depends-On: T23

Objective:
Add a review-friendly architecture diagram image or exported diagram alongside
the existing Mermaid diagram.

Files to create/modify:
- `docs/architecture-diagram.md`
- `docs/CASE_STUDY.md`
- `README.md`

Acceptance Criteria:
1. Diagram shows webhook ingress, signature/rate limit, input guard, LLM tool
   loop, policy/output guard, approval store, execution, audit/cost/metrics,
   Postgres/RLS, Redis, and observability.
2. Diagram is usable in GitHub rendered docs.
3. Diagram does not introduce architecture that is not implemented.

Validation:
- `rg -n "architecture-diagram|webhook|approval|audit|RLS|observability" README.md docs/CASE_STUDY.md`

### [ ] T25: Demo Video Or GIF Checklist

Owner: Human + Codex
Priority: P2
Type: docs
Depends-On: T24

Objective:
Prepare the repo-side checklist and script for recording a short demo artifact.

Files to create/modify:
- `docs/DEMO.md`
- `docs/PORTFOLIO_REVIEW_GUIDE.md`
- `docs/CASE_STUDY.md`

Acceptance Criteria:
1. Demo recording script shows setup, deterministic demo run, audit/approval
   evidence, metrics, and where to inspect tests.
2. Docs state whether the video/GIF artifact exists; if not, they mark it as a
   manual packaging task rather than pretending it is complete.
3. Review guide links to the artifact or checklist.

Validation:
- `rg -n "video|GIF|recording|demo artifact|manual packaging" docs/DEMO.md docs/PORTFOLIO_REVIEW_GUIDE.md docs/CASE_STUDY.md`

### [ ] T26: Resume Bullets With Measured Numbers

Owner: Human + Codex
Priority: P2
Type: docs
Depends-On: T25

Objective:
Create resume-ready bullets grounded in measured repo evidence.

Files to create/modify:
- `docs/RESUME_BULLETS.md`
- `docs/CASE_STUDY.md`

Acceptance Criteria:
1. Bullets mention measured tests, eval baseline, load results, tenant
   isolation, and observability only when linked to evidence.
2. Bullets avoid production-user claims unless backed by real deployment/user
   evidence.
3. Case study links to the bullets as optional hiring packaging.

Validation:
- `rg -n "tests|eval|load|tenant isolation|observability|production-user" docs/RESUME_BULLETS.md docs/CASE_STUDY.md`

### [ ] T27: Final Evidence Audit

Owner: Codex
Priority: P1
Type: docs/tests
Depends-On: T26

Objective:
Close the hardening cycle by verifying the repo can answer the nine final
portfolio questions with links and evidence.

Files to create/modify:
- `docs/EVIDENCE_INDEX.md`
- `docs/PORTFOLIO_REVIEW_GUIDE.md`
- `docs/CASE_STUDY.md`
- `README.md`
- `docs/CODEX_PROMPT.md`

Acceptance Criteria:
1. Evidence index answers: problem, architecture, control boundaries, quality
   evaluation, failure behavior, baseline metrics, demo path, known limits, and
   production changes.
2. README's reviewer path reaches all final evidence in one click.
3. Final state remains bounded as portfolio/pilot evidence, not production SaaS.
4. `docs/CODEX_PROMPT.md` marks hardening complete and points to the final
   review artifacts.

Validation:
- `pytest tests/ -q`
- `ruff check app/ tests/`
- `rg -n "problem|architecture|control boundaries|baseline metrics|known limits|production" docs/EVIDENCE_INDEX.md docs/PORTFOLIO_REVIEW_GUIDE.md docs/CASE_STUDY.md README.md`
