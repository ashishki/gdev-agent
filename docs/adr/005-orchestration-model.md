# ADR-005: Orchestration Model — In-Process APScheduler, Celery as Upgrade Path

**Status:** Accepted
**Date:** 2026-03-03
**Deciders:** Architecture

---

## Context

The platform requires background work beyond the request/response cycle:

1. **RCA Clusterer** — runs every 15 minutes per active tenant; moderate CPU (DBSCAN on
   ≤200 vectors); one LLM call per cluster found.
2. **Cost Aggregator** — runs every hour; simple SQL aggregation; negligible CPU.
3. **Eval Runner** — on-demand or daily; N LLM calls (one per eval case); can take minutes.

The question is how to schedule and execute these jobs. Options range from simple in-process
scheduling to a full task queue system.

**Constraints:**
- Solo engineer; minimize operational surface.
- Must not block API request handlers.
- Must survive application restart without losing pending jobs (or gracefully reschedule).
- Target deployment: single Docker container initially; must be extractable to worker
  containers if scale demands.

---

## Decision

**Use APScheduler (in-process) for scheduled jobs in v1. Design background job interfaces
to be compatible with Celery task signatures to enable extraction later without code rewrites.**

### v1 Implementation

```python
# app/scheduler.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.jobs.rca import run_rca_for_all_tenants
from app.jobs.cost import aggregate_costs

scheduler = AsyncIOScheduler()
scheduler.add_job(run_rca_for_all_tenants, "interval", minutes=15, max_instances=1)
scheduler.add_job(aggregate_costs, "interval", hours=1, max_instances=1)
# EvalRunner: on-demand via POST /eval/run; no scheduler entry
```

APScheduler runs within the FastAPI process. Jobs are coroutines (`async def`); they run on
the event loop but with a dedicated thread pool for blocking DB operations.

### Job Interface Contract (Celery-compatible)

Each job is defined as a standalone async function with no global state:

```python
async def run_rca_for_tenant(tenant_id: str, lookback_hours: int = 24) -> RCAResult:
    ...

# When migrating to Celery, this becomes:
@celery_app.task(name="rca.run_for_tenant")
def run_rca_for_tenant_task(tenant_id: str, lookback_hours: int = 24) -> dict:
    return asyncio.run(run_rca_for_tenant(tenant_id, lookback_hours))
```

The function signature and return type remain stable; only the invocation wrapper changes.

### Migration Trigger

Migrate to Celery + Redis broker when any of:
- RCA job runtime exceeds 60 s per tenant (multi-tenant queues block each other).
- Eval Runner needs to be invoked with retry and result tracking.
- Number of active tenants exceeds 20 (APScheduler max_instances limit per job).

---

## Alternatives Considered

### Alternative A: Celery + Redis Broker (from day 1)
- **Pro:** Production-proven; horizontal worker scaling; retry with backoff; result backend.
- **Con:** Adds `celery` dependency (~8 MB), requires a dedicated worker process, adds
  Flower monitoring for job visibility, and increases Docker Compose complexity significantly.
  For 3 job types at ≤20 tenants, this is engineering overhead with no immediate benefit.
- **Deferred to v2.** Interface contract above ensures no rewrite penalty.

### Alternative B: AWS SQS + Lambda
- **Pro:** Fully managed; scales to zero; no worker processes.
- **Con:** Significant cold start latency for LLM jobs. Lambda timeout (15 min) may be
  tight for large eval runs. Adds AWS-specific dependency, reducing portability.
  Observability integration with OTLP requires Lambda extension.
- **Rejected for v1.** Viable option if migrating fully to serverless later.

### Alternative C: Temporal (workflow orchestrator)
- **Pro:** Durable execution; replay semantics; built for long-running jobs.
- **Con:** Requires a Temporal server; steep learning curve; significant operational overhead.
  Complete overkill for 3 job types at current scale.
- **Rejected.** Not appropriate for a 4–6 week solo build.

### Alternative D: Cron via Docker Compose (separate container)
- **Pro:** Simple; no Python dependency.
- **Con:** No retry logic. No shared application context (must re-initialize DB connections).
  Output not captured in structured logs. Not testable in unit tests. Terrible developer UX.
- **Rejected.**

---

## Consequences

**Positive:**
- Zero additional infrastructure in v1.
- Jobs are testable: plain async functions callable in tests.
- APScheduler `max_instances=1` prevents overlapping runs of the same job.
- Migration to Celery is a well-defined, low-risk step with no interface changes.
- Job interface is documented here; any engineer can execute the migration.

**Negative / Risks:**
- APScheduler jobs share the FastAPI process. A runaway RCA job (e.g., large tenant,
  slow LLM) could consume CPU and affect API latency.
  Mitigate: async jobs with timeout wrappers (`asyncio.wait_for(job(), timeout=120)`).
- APScheduler state is in-memory. A restart clears the schedule; jobs reschedule on next
  interval. For 15-minute RCA jobs, this is acceptable (worst case: 15-minute gap).
- Eval Runner is on-demand, not scheduled; does not suffer from the above.

**Review date:** Evaluate migration to Celery when tenant count exceeds 10 or RCA runtime
exceeds 30 s per run.
