# Load Profile v1.0

_Date: 2026-03-03_
_Load scenarios define performance expectations and failure boundaries. Update this document
before load testing. Use Locust for execution._

---

## System Topology Assumptions (for these scenarios)

- 1 FastAPI instance (2 vCPU, 4 GB RAM; AWS t3.medium equivalent).
- 1 Postgres instance (2 vCPU, 8 GB RAM; RDS db.t3.medium).
- 1 Redis instance (t3.micro; ElastiCache or self-hosted).
- Anthropic API: external dependency. Not load-tested by us; treat as a variable-latency
  black box (p50 ≈ 1.2 s, p99 ≈ 4 s, rate limit: 50 RPM on Sonnet tier).
- Up to 10 tenants active simultaneously in steady-state scenario.

---

## Scenario A: Burst Intake

### Description
A game server event (patch release, weekend event, major bug) causes a sudden flood of player
support messages over 5–10 minutes. This is the most common high-load pattern for live-service
games.

### Load Shape
```
Ramp: 0 → 60 RPS over 60 s
Hold: 60 RPS for 300 s
Ramp down: 60 → 0 over 60 s
Total duration: 420 s (~7 min)
Distribution: 80 % POST /webhook, 10 % POST /approve, 10 % GET /tickets
Tenants: 3 concurrent (simulating a multi-tenant burst)
```

### Expected Behavior
- Rate limiter (10 RPM per user, sliding window) absorbs excess from individual users.
- Requests over the rate limit return HTTP 429 immediately (< 5 ms).
- Valid requests enter the LLM queue; Anthropic rate limit (50 RPM) becomes the bottleneck
  before the application layer.
- Expected queue depth: up to 10 requests waiting for Anthropic API at peak.
- p50 latency: < 2 s (LLM-bound).
- p99 latency: < 8 s (includes Anthropic rate limit wait + retries).
- Error rate: < 1 % (429s excluded; these are expected behavior, not errors).

### Failure Thresholds
| Condition | Response |
|---|---|
| Anthropic 529 (overloaded) | tenacity retry (max 3, backoff 2–8 s); 503 if all fail |
| Redis unavailable | Fall back to Postgres-only pending; log degraded mode alert |
| Postgres write queue > 50 ms p99 | Alert; scale up RDS read replica |
| API error rate (5xx) > 2 % | Page on-call; investigate LLM retry saturation |

### Performance KPIs
| KPI | Target | Failure Threshold |
|---|---|---|
| POST /webhook p50 | < 2.0 s | > 4.0 s |
| POST /webhook p99 | < 8.0 s | > 15.0 s |
| HTTP 5xx rate | < 1 % | > 3 % |
| HTTP 429 rate | Expected; < 30 % total | > 60 % (rate limit too aggressive) |
| LLM retry rate | < 20 % | > 40 % |

---

## Scenario B: Steady QPS

### Description
Normal business hours for a medium game studio. Steady flow of player messages across multiple
channels. System must sustain this indefinitely without memory leaks, connection exhaustion,
or cost overruns.

### Load Shape
```
Ramp: 0 → 8 RPS over 120 s
Hold: 8 RPS for 3600 s (1 hour)
Distribution: 70 % POST /webhook, 15 % POST /approve, 15 % GET /tickets|clusters|audit
Tenants: 10 concurrent
User distribution: 50 unique users across all tenants
```

### Expected Behavior
- All requests served within SLA.
- No memory growth over 1-hour hold (measure FastAPI process RSS before and after).
- Redis connection pool stable (no connection leak).
- Postgres connection pool stable (max 10 connections; pgBouncer in front).
- RCA Clusterer runs 4 times during hold; each run < 30 s; no API latency impact.
- Cost ledger accurately reflects accumulated costs; no drift vs. sum of audit_log.

### Performance KPIs
| KPI | Target | Failure Threshold |
|---|---|---|
| POST /webhook p50 | < 1.5 s | > 3.0 s |
| POST /webhook p99 | < 5.0 s | > 10.0 s |
| GET /tickets p99 | < 200 ms | > 1.0 s |
| GET /clusters p99 | < 500 ms | > 2.0 s |
| HTTP 5xx rate | < 0.1 % | > 1 % |
| Memory growth (RSS) | < 10 % over 1 h | > 30 % |
| DB connection count | ≤ 10 | > 20 |
| Cost per request (avg) | < $0.015 | > $0.02 |

---

## Scenario C: Heavy Clustering Batch Job

### Description
The RCA Clusterer processes a large backlog: a tenant has 48 hours of unprocessed tickets
(e.g., after a system outage or a first onboarding). The batch job runs alongside normal
steady traffic. This tests whether background workers cause resource contention.

### Load Shape
```
Background job: RCA Clusterer over 2000 tickets for 1 tenant, triggered manually
Concurrent: 4 RPS steady POST /webhook across other 5 tenants
Duration: job completes + 10 min cooldown observation
```

### Expected Behavior
- RCA Clusterer completes within 5 minutes for 2000 tickets (pgvector ANN: ≈ 500 ms;
  DBSCAN: < 1 s for 2000 points; LLM summarize per cluster: ≈ 1.5 s × N clusters).
- Estimated worst case: 30 clusters × 2 s LLM = 60 s LLM time + 30 s vector queries = < 2 min.
- API p99 for concurrent webhooks must not degrade by more than 20 % vs. Scenario B.
- No DB connection exhaustion (RCA job uses its own connection from the pool).
- RCA job timeout wrapper (`asyncio.wait_for(timeout=300)`) fires if job exceeds 5 min.

### Failure Thresholds
| Condition | Response |
|---|---|
| RCA job > 5 min | `asyncio.wait_for` cancels; log `rca_timeout`; reschedule |
| pgvector ANN query > 2 s | Log slow query; consider reducing `lookback_hours` |
| > 50 clusters found | Cap at 50; log `rca_cluster_cap_hit`; alert tenant_admin |
| API p99 degradation > 30 % | Kill RCA job; restrict to off-hours schedule |

### Performance KPIs
| KPI | Target | Failure Threshold |
|---|---|---|
| RCA job completion time | < 5 min for 2000 tickets | > 10 min |
| API p99 degradation during RCA | < 20 % vs. baseline | > 30 % |
| Clusters produced | Proportional (≈ 5–30 for 2000 diverse tickets) | > 50 (cap triggered) |
| LLM cost per RCA run | < $0.10 (30 clusters × $0.003) | > $0.50 |
| DB connection count during RCA | ≤ 15 | > 25 |

---

## Load Testing Tooling

**Tool:** Locust (Python-native; integrates with existing test infrastructure).

**Locust file structure:**
```
load_tests/
  locustfile.py         — defines User classes for each scenario
  scenarios/
    burst.py            — Scenario A
    steady.py           — Scenario B
    batch.py            — Scenario C
  fixtures/
    sample_messages.jsonl  — realistic player support messages (synthetic)
```

**Execution:**
```bash
# Scenario A (burst)
locust -f load_tests/locustfile.py --scenario burst \
  --headless -u 60 -r 10 --run-time 7m \
  --host http://localhost:8000

# Scenario B (steady)
locust -f load_tests/locustfile.py --scenario steady \
  --headless -u 50 -r 5 --run-time 1h \
  --host http://localhost:8000
```

**Result capture:**
- Locust HTML report + CSV stats.
- Prometheus metrics snapshot at start and end of run.
- Grafana dashboard screenshot at hold peak.
- Results stored in `load_tests/results/{date}/`.

---

## Throughput Ceiling Estimate

Given Anthropic Sonnet at 50 RPM with p50 latency 1.2 s:
- Maximum sustainable throughput (LLM-bound): ≈ 40–45 RPS if all requests hit the LLM.
- Non-LLM requests (GET /tickets, GET /clusters, POST /approve): limited by Postgres query
  time (< 50 ms) and FastAPI concurrency (asyncio). Upper bound: > 200 RPS.
- Effective system ceiling: **≈ 40 RPS** before Anthropic rate limit becomes the hard wall.
- Mitigation: request queuing (accept request, queue LLM call, return pending) —
  this is already the architecture for risky=True actions. Extend to all actions if needed.
