# Load Test Report

Date: 2026-06-12

This report is local deterministic/synthetic portfolio evidence. It proves that
the load harness, KPI checker, and reporting path are reproducible, but it does
not claim production capacity, external deployment performance, or live tenant
traffic.

## Local Environment

- Repository: `gdev-agent`
- Branch baseline: `master`
- Python: project `.venv`
- Runtime mode for reproducible review: `LLM_MODE=demo`
- Baseline verification before this report: `260 passed, 42 warnings`
- Live dependencies for an actual Locust run: local Docker Compose FastAPI,
  Redis, and Postgres stack from `docker-compose.yml`

## Commands

Deterministic report fixture:

```bash
.venv/bin/python load_tests/check_kpis.py --dry-run
```

Local live run path, when the Compose stack is running:

```bash
LLM_MODE=demo docker compose up --build -d
.venv/bin/python scripts/demo.py --llm-mode demo

mkdir -p load_tests/results/local
.venv/bin/locust -f load_tests/locustfile.py --scenario low_load \
  --headless -u 5 -r 1 --run-time 2m \
  --host http://localhost:8000 \
  --csv load_tests/results/local/low_load

.venv/bin/python load_tests/check_kpis.py \
  --stats load_tests/results/local/low_load_stats.csv \
  --failures load_tests/results/local/low_load_failures.csv
```

Full scenario commands are maintained in [load-profile.md](load-profile.md).

## Scenario Configuration

| Scenario | Tenants | Purpose | Default shape |
| --- | ---: | --- | --- |
| `low_load` | 1 | Compose-safe smoke load | 5 users, 1 spawn/s, 2m |
| `mixed_10_tenant` | 10 | Mixed tenant support traffic | 50 users, 5 spawn/s, 10m |
| `duplicate_replay` | 1 | Replay/idempotency pressure | 20 users, 10 spawn/s, 2m |
| `risky_action_heavy` | 2 | Approval-heavy traffic | 20 users, 4 spawn/s, 5m |
| `provider_latency` | 2 | Provider-latency simulation | 15 users, 3 spawn/s, 5m |

The scenario matrix is defined in
[`load_tests/locustfile.py`](../load_tests/locustfile.py) and backed by
synthetic messages in
[`load_tests/fixtures/sample_messages.jsonl`](../load_tests/fixtures/sample_messages.jsonl).

## Results

Source artifact:
[`scenario_results.csv`](../load_tests/results/local-deterministic-2026-06-12/scenario_results.csv).

| Scenario | p50 | p95 | p99 | Error rate | Approval creation rate | Dedup hit rate | Guard block rate | Est. cost/request |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `low_load` | 120 ms | 480 ms | 900 ms | 0.00% | 18.00% | 8.00% | 4.00% | $0.000800 |
| `mixed_10_tenant` | 210 ms | 720 ms | 1300 ms | 0.00% | 22.00% | 3.00% | 3.00% | $0.000820 |
| `duplicate_replay` | 80 ms | 160 ms | 260 ms | 0.00% | 0.00% | 96.00% | 0.00% | $0.000000 |
| `risky_action_heavy` | 190 ms | 650 ms | 1200 ms | 0.00% | 71.00% | 2.00% | 1.00% | $0.000850 |
| `provider_latency` | 870 ms | 1220 ms | 1740 ms | 0.00% | 26.00% | 2.00% | 2.00% | $0.000830 |

The dry-run KPI checker output is committed at
[`kpi_dry_run.txt`](../load_tests/results/local-deterministic-2026-06-12/kpi_dry_run.txt).

## Redis And Postgres Notes

- Redis behavior covered by the harness: tenant-key separation, dedup key reuse
  in `duplicate_replay`, approval queue growth in `risky_action_heavy`, and
  rate-limit pressure in live runs.
- Postgres behavior covered by the harness path: ticket/audit/cost writes after
  successful execution and pending approval persistence after risky actions.
- These committed results do not measure Redis latency, Postgres p99 write
  latency, connection pool pressure, or container memory. A live local Locust run
  must collect those before making throughput claims.

## Interpretation

The evidence is useful for review because it proves the project has a bounded
load harness, synthetic fixtures, KPI reporting, and scenario-specific expected
signals. The duplicate replay and risky-action profiles map directly to the
failure-mode work from Phase 3.

The evidence is not a production benchmark. It does not include external
traffic, paid LLM calls, cloud networking, managed database latency, multi-node
coordination, or sustained one-hour soak data.

## Known Limits

- Results are local deterministic/synthetic, not a production SLA.
- The 10-tenant profile requires matching synthetic tenants seeded locally
  before a live run.
- Provider latency is simulated in the Locust user, not measured against a live
  provider.
- Redis and Postgres notes identify expected pressure points; they are not
  measured infrastructure metrics in this committed fixture.
- Use [SLO_RUNBOOK.md](SLO_RUNBOOK.md) and [FAILURE_MODES.md](FAILURE_MODES.md)
  to interpret failures before changing thresholds.
