---
# ARCH_REPORT — Cycle 8
_Date: 2026-03-09_

## Component Verdicts

| Component | Verdict | Note |
|-----------|---------|------|
| eval subsystem — `POST /eval/run` / `GET /eval/runs` (T22) | VIOLATION | `app/routers/eval.py` does not exist; T22 not implemented |
| eval runner extension (T22) | VIOLATION | `eval/runner.py` lacks: `db_session` param, eval isolation flag, CostLedger integration, `eval_runs` persistence |
| load test harness — `load_tests/` (T23) | VIOLATION | Directory does not exist; T23 not implemented |
| docker-compose full stack (T24) | DRIFT | Prometheus + Grafana present; Loki and Grafana Tempo absent; OTLP Collector absent |
| `app/agent.py` — service layer | VIOLATION | Imports `HTTPException` from `fastapi` (transport type leak, ARCH-7 open) |
| `app/routers/auth.py` — route layer | DRIFT | Route handler contains business logic: bcrypt, JWT minting, raw DB queries (ARCH-8 open) |
| `GET /metrics` — auth contract | DRIFT | Exempt from JWTMiddleware; unreconciled with spec §5 security assumption 2 (ARCH-5 open) |
| `app/middleware/auth.py` — JWT validation | PASS | HS256 blocklist enforcement correct; ARCH-1 closed |
| `app/middleware/rate_limit.py` — rate limiting | PASS | Sliding window per user; Retry-After header present |
| `app/middleware/signature.py` — HMAC auth | PASS | Per-tenant secret with Fernet decrypt |
| APScheduler — background jobs | DRIFT | `max_instances=1` absent from `scheduler.add_job` call (ARCH-12 new); runaway-job protection implicit only |
| `app/jobs/rca_clusterer.py` — RCA pipeline | DRIFT | LLM summarization bypasses CostLedger (ARCH-3 open); blocking sync call in async path (CODE-9 open) |
| Postgres + RLS | PASS | pgvector image, RLS migrations, tenant context via `SET LOCAL` |
| Redis — key namespace | DRIFT | Actual keys lack `{tenant_id}:` prefix mandated by spec §5 item 4 and data-map §3 (CODE-11 open) |
| pgvector — embedding model | DRIFT | ADR-002 specifies `VECTOR(1536)` / `text-embedding-3-small`; runtime is `VECTOR(1024)` / `voyage-3-lite` (ARCH-2 open) |

---

## ADR Compliance

| ADR | Verdict | Note |
|-----|---------|------|
| ADR-001 Storage: PostgreSQL + RLS + Redis | DRIFT | Storage topology correct; Redis key namespace lacks tenant prefix (CODE-11); spec §5 item 4 violated |
| ADR-002 Vector DB: pgvector conditional | DRIFT | Decision specifies `VECTOR(1536)` + OpenAI `text-embedding-3-small`; data-map and config use `VECTOR(1024)` + `voyage-3-lite`; ADR not updated (ARCH-2) |
| ADR-003 RBAC: JWT roles / HS256 | PASS | ADR-003 explicitly adopted HS256 v1; ARCH-1 closed Cycle 8 |
| ADR-004 Observability: OTel + Prometheus + Loki + Grafana | DRIFT | OTel spans and Prometheus metrics implemented; docker-compose.yml missing Loki, Grafana Tempo, OTLP Collector (ARCH-11 new) |
| ADR-005 Orchestration: APScheduler + Claude tool_use ≤5 turns | DRIFT | `max_instances=1` absent from `scheduler.add_job` at `app/main.py:181` (ARCH-12 new); ADR-005 requires it explicitly |

---

## Architecture Findings

### ARCH-9 [P1] — T22 eval subsystem not implemented
Symptom: `POST /eval/run` and `GET /eval/runs` required by spec §8 are absent.
Evidence: `app/routers/eval.py` — file does not exist; `app/main.py:238` — no eval router registered.
Root cause: T22 not yet started; router, service integration, and `eval_runs` persistence all missing.
Impact: Spec §9 regression gate ("No eval run may drop F1 by > 0.02 vs. prior run without alert") is unenforceable. ARCH-3 intersection unresolved: eval LLM calls do not flow through CostLedger.
Fix: Implement `app/routers/eval.py` with `POST /eval/run` (JWT `tenant_admin`) and `GET /eval/runs` (JWT any role); extend `eval/runner.py` with `db_session` param, eval isolation flag (`suppress_ticket_writes=True`, skip Linear/Telegram), `CostLedger.check_budget()` + `record()` under `category="eval"`, and `eval_runs` table persistence; register router in `app/main.py`.

### ARCH-10 [P2] — T23 load test harness not implemented
Symptom: `load_tests/` directory expected by Cycle 8 scope does not exist.
Evidence: `load_tests/` — directory not found; no `locustfile.py`, `check_kpis.py`, or HMAC signing fixture.
Root cause: T23 not yet started.
Impact: No automated KPI gate (p50 < 2 s, p99 < 8 s, 5xx < 1 %); CODE-9 (blocking sync summarize) and CODE-11 (un-namespaced Redis keys) carry elevated risk with no regression harness to surface them.
Fix: Create `load_tests/locustfile.py` (steady + burst scenarios), `load_tests/check_kpis.py` (KPI assertions), HMAC signing fixture under `load_tests/fixtures/`; wire into CI.

### ARCH-11 [P2] — docker-compose.yml missing Loki and Grafana Tempo (T24 partial)
Symptom: T24 scope includes Loki and Tempo; current `docker-compose.yml` has neither.
Evidence: `docker-compose.yml` services: postgres, agent, redis, prometheus, grafana, n8n — Loki/Promtail and Tempo absent.
Root cause: T24 partially applied; only the Prometheus + Grafana slice landed.
Impact: ADR-004 DRIFT confirmed. No log aggregation or distributed trace backend in the dev stack. OTel spans have no receiver locally; trace-to-log correlation not exercisable.
Fix: Add `loki`, `promtail`, and `tempo` services to `docker-compose.yml`; add OTLP Collector service or configure direct OTLP export to Tempo (`OTLP_ENDPOINT=http://tempo:4318` in dev env). Use `--profile observability` flag to keep default compose lightweight (ADR-004 mitigation).

### ARCH-12 [P2] — APScheduler `max_instances=1` not enforced (ADR-005 drift)
Symptom: ADR-005 explicitly requires `max_instances=1` on the RCA job to prevent overlapping runs; the actual call omits it.
Evidence: `app/main.py:181` — `scheduler.add_job(rca_clusterer.run_with_timeout, "interval", minutes=15, id="rca_clusterer")` — no `max_instances` kwarg; ADR-005 decision sample requires it.
Root cause: Implementation omitted the guard; APScheduler `AsyncIOScheduler` defaults to `max_instances=1` implicitly but this is not documented behaviour to rely upon.
Impact: If APScheduler version or job type changes, overlapping RCA runs could fire simultaneously, doubling LLM cost and creating DB write conflicts on `cluster_summaries`.
Fix: Add `max_instances=1` explicitly to the `scheduler.add_job` call.

### ARCH-2 [P2] — ADR-002 vector stack drift: OpenAI/1536 vs Voyage/1024 (carry-forward)
Symptom: ADR-002 specifies `VECTOR(1536)` and `text-embedding-3-small`; runtime uses `VECTOR(1024)` / `voyage-3-lite`.
Evidence: `docs/adr/002-vector-database.md:32` (`VECTOR(1536)`, `text-embedding-3-small`); `docs/data-map.md:116` (`VECTOR(1024)`, `voyage-3-lite`); `app/config.py:29` (Voyage model).
Root cause: Embedding model switched post-ADR; ADR not updated.
Impact: ADR is the authoritative decision record; stale content misleads future engineers and auditors.
Fix: Update ADR-002 Decision section: dimension → 1024, model → `voyage-3-lite`, update cost and index memory estimates. Status remains Accepted.

### ARCH-3 [P2] — eval LLM calls bypass CostLedger (carry-forward + T22 intersection)
Symptom: `eval/runner.py` instantiates `AgentService` with `fakeredis` and no DB session; LLM calls during eval do not pass through `CostLedger.check_budget()` or `record()`.
Evidence: `eval/runner.py:39-40` — `AgentService(settings=settings, store=EventStore(sqlite_path=None), approval_store=...)` — no `db_session_factory`; `app/agent.py:151` — CostLedger requires DB session.
Root cause: `eval/runner.py` is a standalone script predating the CostLedger service; never extended for budget tracking.
Impact: Eval runs can exhaust per-tenant LLM budgets silently; no cost accounting for eval workload.
Fix: Resolved by ARCH-9 — new `POST /eval/run` endpoint must inject `db_session_factory` and call `CostLedger.record()` under `category="eval"`.

### ARCH-5 [P2] — `/metrics` auth exemption not reconciled with spec security contract (carry-forward)
Symptom: `GET /metrics` is in `JWTMiddleware`'s exempt set; spec §5 item 2 states "All API calls require a JWT Bearer token."
Evidence: `app/middleware/auth.py:54` — `("GET", "/metrics")` in exempt set; `docs/spec.md:91` — security assumption 2.
Root cause: Prometheus scrape model cannot carry JWT tokens; exemption added pragmatically without updating the spec.
Impact: Metrics endpoint publicly accessible on the service port; in production a misconfigured network boundary could expose tenant-level counters.
Fix: Option A — add carve-out note to spec.md §5 item 2 ("Prometheus scrape path is network-protected; JWT exemption intentional"); Option B — add optional bearer-token guard via `METRICS_AUTH_TOKEN` env var. Document chosen approach in both spec and middleware.

### ARCH-7 [P2] — `app/agent.py` imports `HTTPException` (transport type) — service/transport boundary violation (carry-forward)
Symptom: Service layer imports a FastAPI HTTP response type.
Evidence: `app/agent.py:15` — `from fastapi import HTTPException`.
Root cause: Error propagation convenience; HTTPException used to surface 400/401 errors from within the service.
Impact: Service layer coupled to FastAPI; cannot be reused in non-HTTP contexts (CLI eval runner, background jobs).
Fix: Define domain exceptions in `app/exceptions.py`; catch and map to HTTPException in route handlers only.

### ARCH-8 [P2] — Router layer carries business logic that belongs in service layer (carry-forward)
Symptom: `app/routers/auth.py` contains bcrypt verification, JWT minting, raw SQL, and constant-time dummy hash — all service-layer concerns.
Evidence: `app/routers/auth.py:26-96` — entire business flow inline in route handler; `app/main.py:275` — tenant_id resolution and dedup logic inline in webhook handler.
Root cause: Incremental additions without extracting service layers.
Impact: Route handlers untestable without HTTP context; business logic cannot be reused; instrumentation scattered.
Fix: Extract `AuthService.authenticate(email, password, tenant_slug, db_session) -> JWT`; call from route handler only.

---

## Doc Patches Needed

| File | Section | Change |
|------|---------|--------|
| `docs/ARCHITECTURE.md` | Version header | Bump v2.1 → v3.0; record Phase 6 (T19–T21) complete; add Phase 7 scope |
| `docs/ARCHITECTURE.md` | Component Status table | Add eval subsystem (T22: unimplemented), load test harness (T23: unimplemented), docker-compose T24 (partial) rows |
| `docs/adr/002-vector-database.md` | Decision section | Update `VECTOR(1536)` → `VECTOR(1024)`; `text-embedding-3-small` → `voyage-3-lite`; update cost/memory estimates |
| `docs/spec.md` | §5 Security Assumptions item 2 | Add carve-out for `/metrics` Prometheus exemption with rationale |
| `docs/data-map.md` | §3 Redis Key Schema | Mark keys as pending CODE-11 fix; confirm tenant-namespaced format once resolved |

---
_ARCH_REPORT.md written. Run PROMPT_2_CODE.md._
