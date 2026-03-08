---
# ARCH_REPORT — Cycle 4
_Date: 2026-03-08_

---

## Component Verdicts

| Component | Verdict | Note |
|-----------|---------|------|
| `app/embedding_service.py` | PASS | Layer clean; OTel + Prometheus; VECTOR(1024)/voyage-3-lite; RLS SET LOCAL correct; `raise` on failure isolated by `create_task` in caller |
| `app/jobs/rca_clusterer.py` | DRIFT | No OTel spans (Prometheus only); timeout 300 s vs ADR-005 example 120 s; budget approximation bypasses `CostLedger` |
| `app/routers/clusters.py` | PASS | RLS via `get_db_session`; `require_role("viewer", …)` on both endpoints; cross-tenant 404 via `AND tenant_id = :tenant_id`; no cost/audit exposure; ticket_ids heuristic noted |
| `alembic/versions/0004` | PASS | Conditional pgvector check retained; upgrade 1536→1024, downgrade 1024→1536 both guarded |
| `app/agent.py` | VIOLATION | P2-6 carry-forward: `from fastapi import HTTPException` at line 15 — service layer must not import from presentation framework |
| `app/config.py` | VIOLATION | P1-1 carry-forward: `jwt_algorithm = "HS256"` (line 49); ADR-003 mandates RS256; new fields `embedding_model`, `rca_lookback_hours`, `rca_budget_per_run_usd` present and correct |
| `app/llm_client.py` | PASS | `summarize_cluster()` (line 238) is a single-call path with no tool_use loop; `max_turns=5` enforced in main `run()` |
| `app/main.py` | DRIFT | P2-10 carry-forward: `get_settings()` at module level (line 179) requires `ANTHROPIC_API_KEY` at import time; APScheduler registration correct |
| `app/schemas.py` | PASS | New cluster/embedding schemas do not bleed business logic into presentation layer |

---

## ADR Compliance

| ADR | Verdict | Note |
|-----|---------|------|
| ADR-001 Storage: PostgreSQL + RLS + Redis | PASS | All new components write to Postgres; `SET LOCAL app.current_tenant_id` used in EmbeddingService; Redis keys unchanged (P2-1 deferred carry-forward) |
| ADR-002 Vector DB: pgvector conditional | DRIFT | ADR-002 specifies `text-embedding-3-small` (OpenAI, 1536-dim). Implementation uses Voyage AI voyage-3-lite (1024-dim). `data-map.md` updated; ADR-002 text is stale |
| ADR-003 RBAC: RS256 mandated | VIOLATION | `jwt_algorithm = "HS256"` (config.py:49). RS256 + JWKS not implemented. P1-1 open since Cycle 1 |
| ADR-004 Observability: OTel + Prometheus | DRIFT | EmbeddingService: full OTel + Prometheus. RCAClusterer: Prometheus only — no OTel trace spans. Cluster API router: no spans or metrics |
| ADR-005 Orchestration: tool_use ≤5 turns + APScheduler | DRIFT | Tool_use ≤5 turns: PASS. APScheduler registration: PASS. Timeout: ADR-005 documents `timeout=120`; implementation uses `timeout=300` (all tenants combined) |

---

## Architecture Findings

### ARCH-1 [P1] — RS256 Mandated by ADR-003; HS256 Still Implemented
Symptom: JWT signing algorithm is HS256 (symmetric). No JWKS endpoint exists.
Evidence: `app/config.py:49` — `jwt_algorithm: str = "HS256"`; `docs/adr/003-rbac-design.md` §Decision — "JWT signed with RS256 (asymmetric). Public key published at `/auth/jwks.json`."
Root cause: Deferred architectural decision — HS256 was shipped as a simpler v1 shortcut; key rotation requires redeploy.
Impact: No key rotation without downtime; no standard JWKS discovery; incompatible with OAuth2 / external IdP migration path described in ADR-003 §Alternatives.
Fix: Architecture decision required before Phase 5 if auth is touched. Options: (a) accept HS256 and amend ADR-003; (b) implement RS256 with JWKS endpoint. Either path must be recorded in a new ADR or ADR-003 amendment.

### ARCH-2 [P2] — ADR-002 Stale: Voyage AI / 1024-dim Not Documented
Symptom: ADR-002 specifies `text-embedding-3-small` (OpenAI, 1536-dim). Actual implementation and `data-map.md` use voyage-3-lite (Voyage AI, 1024-dim).
Evidence: `docs/adr/002-vector-database.md` §Decision — "embedding VECTOR(1536)… text-embedding-3-small (OpenAI)"; `docs/data-map.md` §ticket_embeddings — "VECTOR(1024) — voyage-3-lite pinned model"; `app/config.py:29` — `embedding_model: str = "voyage-3-lite"`.
Root cause: ADR-002 was not updated when the embedding model decision changed (T13).
Impact: ADR-002 is the authoritative model decision record; mismatched text creates confusion about what model is in use and why.
Fix: Update ADR-002 to reflect Voyage AI voyage-3-lite, 1024-dim decision. Document rationale (cost, no OpenAI dependency, pinned model dimension).

### ARCH-3 [P2] — RCAClusterer Missing OTel Trace Spans
Symptom: RCAClusterer emits Prometheus metrics but no OpenTelemetry spans.
Evidence: `app/jobs/rca_clusterer.py` — no `trace.get_tracer()` or span context; `app/embedding_service.py:85` — `with TRACER.start_as_current_span("service.embedding_service.upsert")` shows the expected pattern; ADR-004 §Instrumentation Scope — `agent.embed (async; linked trace)` expected.
Root cause: OTel instrumentation omitted during T14 implementation.
Impact: No distributed trace linkage from `/webhook` → embedding → RCA run; no per-tenant RCA latency visibility in Grafana Tempo.
Fix: Add OTel tracer to RCAClusterer following the same noop-fallback pattern as EmbeddingService. Instrument `run_tenant()` and `_upsert_cluster()`.

### ARCH-4 [P2] — RCAClusterer Budget Check Bypasses CostLedger
Symptom: LLM calls in `_upsert_cluster()` are gated by a cluster count cap, not by `CostLedger.check_budget()`.
Evidence: `app/jobs/rca_clusterer.py:164-180` — `budget_cap = max(1, min(50, int(rca_budget_per_run_usd / Decimal("0.003"))))` used to cap clusters before LLM calls; no import or call to `CostLedger`.
Root cause: RCAClusterer approximates cost via a static cluster count rather than integrating with the per-tenant budget enforcement path.
Impact: LLM cost from RCA summarization is not recorded in `cost_ledger` and not counted against the tenant's daily budget. A tenant with a tight daily budget could have its quota exceeded by RCA runs without the budget guard triggering.
Fix: Call `CostLedger.check_budget(tenant_id)` before LLM summarization per cluster; record actual cost via `CostLedger.record()` after each `summarize_cluster()` call.

### ARCH-5 [P3] — RCA Job Timeout 300 s vs ADR-005 Example 120 s
Symptom: `run_with_timeout()` uses `timeout=300` for all tenants combined.
Evidence: `app/jobs/rca_clusterer.py:120` — `asyncio.wait_for(self.run_for_all_tenants(), timeout=300)`; ADR-005 §Consequences — "async jobs with timeout wrappers (`asyncio.wait_for(job(), timeout=120)`)".
Root cause: ADR-005 lists 120 s as an example; 300 s may be intentional for multi-tenant coverage. No explicit decision recorded.
Impact: A runaway RCA run consuming up to 5 minutes could degrade API latency (shared event loop). Risk is low for ≤10 tenants but increases linearly.
Fix: Document the 300 s choice in ADR-005 or a follow-up note. Consider per-tenant timeout (`asyncio.wait_for(run_tenant(tid), timeout=30)`) to prevent single-tenant pathology from blocking others.

### ARCH-6 [P2] — Cluster Detail ticket_ids Returns Time-Window Approximation
Symptom: `GET /clusters/{id}` returns ticket IDs from `ticket_embeddings` by timestamp range, not actual cluster membership.
Evidence: `app/routers/clusters.py:152-175` — query selects from `ticket_embeddings WHERE created_at BETWEEN first_seen AND last_seen`; cluster membership is not stored; `cluster_summaries` has no `ticket_ids[]` column.
Root cause: Cluster membership is not persisted; the schema has no cluster-to-ticket join table.
Impact: Returned ticket_ids may include tickets from other clusters active in the same time window and may miss cluster members outside that window. API contract is misleading — callers cannot reliably reconstruct cluster composition.
Fix (two options): (a) Add `cluster_ticket_memberships` join table in a new migration and populate during `_upsert_cluster()`; (b) Document the heuristic in the API response schema and API docs so callers understand the approximation. Option (a) is architecturally correct; (b) is the minimum viable fix.

---

## Doc Patches Needed

| File | Section | Change |
|------|---------|--------|
| `docs/adr/002-vector-database.md` | §Decision | Replace `text-embedding-3-small` / `VECTOR(1536)` / "OpenAI" with `voyage-3-lite` / `VECTOR(1024)` / "Voyage AI"; update volume estimate for 1024-dim; document model selection rationale |
| `docs/ARCHITECTURE.md` | §2.1 Component Status | Add rows for EmbeddingService, RCAClusterer, Cluster API (`/clusters`, `/clusters/{id}`), Migration 0004; bump doc version to v3.0 |
| `docs/ARCHITECTURE.md` | §6 or new §8 Background Jobs | Add section describing APScheduler registration, RCAClusterer lifecycle, and EmbeddingService fire-and-forget pattern |
| `docs/adr/005-orchestration-model.md` | §Consequences | Clarify 300 s timeout rationale for multi-tenant combined run; update example from 120 s or explain difference |

---

_When done: "ARCH_REPORT.md written. Run PROMPT_2_CODE.md."_
