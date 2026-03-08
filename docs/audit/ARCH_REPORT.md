---
# ARCH_REPORT — Cycle 5
_Date: 2026-03-08_

---

## Component Verdicts

| Component | Verdict | Note |
|-----------|---------|------|
| `app/jobs/rca_clusterer.py` | DRIFT | FIX-6 ✅ resolved (ValueError + LOGGER.error); FIX-7 ✅ resolved (SET LOCAL in all 4 session contexts); Prometheus metrics added; OTel trace spans still absent (ARCH-3 open); CostLedger bypass (ARCH-4 open); 300 s timeout (ARCH-5 open) |
| `app/embedding_service.py` | PASS | Carry-forward from Cycle 4 — OTel + Prometheus; RLS SET LOCAL correct |
| `app/routers/clusters.py` | DRIFT | Timestamp heuristic in `GET /clusters/{id}` (ARCH-6 open); violates spec.md §8 API contract for member tickets |
| `app/middleware/auth.py` | VIOLATION | P1-1 carry-forward: HS256 implemented; RS256 + JWKS not present; ADR-003 mandates RS256 |
| `app/agent.py` | VIOLATION | P2-6 carry-forward: `from fastapi import HTTPException` at line 15 — service layer must not import from presentation framework |
| `app/config.py` | VIOLATION | P1-1 carry-forward: `jwt_algorithm: str = "HS256"` at line 49 |
| `app/llm_client.py` | PASS | Tool-use loop enforced at ≤5 turns; `summarize_cluster()` is a single-call path with no tool_use loop |
| `app/main.py` | DRIFT | P2-10 carry-forward: `get_settings()` at module level (line 179) requires `ANTHROPIC_API_KEY` at import time |
| `app/schemas.py` | PASS | Cluster/embedding schemas do not bleed business logic into presentation layer |

---

## ADR Compliance

| ADR | Verdict | Note |
|-----|---------|------|
| ADR-001 Storage: PostgreSQL + RLS + Redis | DRIFT | Postgres writes correct; SET LOCAL present in all session contexts (FIX-7 resolved). Redis keys in `dedup.py` and `approval_store.py` are NOT tenant-namespaced — P2-1 deferred carry-forward; contradicts data-map.md §3 |
| ADR-002 Vector DB: pgvector conditional | DRIFT | ADR-002 specifies `text-embedding-3-small` / `VECTOR(1536)` / OpenAI; implementation and data-map.md use `voyage-3-lite` / `VECTOR(1024)` / Voyage AI — doc fix only (ARCH-2 open) |
| ADR-003 RBAC: RS256 mandated | VIOLATION | `jwt_algorithm = "HS256"` (config.py:49). RS256 + JWKS endpoint not implemented. P1-1 open since Cycle 1 |
| ADR-004 Observability: OTel + Prometheus | DRIFT | `feat(metrics)` commit added Prometheus metrics to RCAClusterer (§2.5 satisfied). OTel root traces for background jobs (observability.md §3.2) still missing in RCAClusterer. Cluster API router has no spans or metrics. ARCH-3 partially resolved |
| ADR-005 Orchestration: tool_use ≤5 turns + APScheduler | DRIFT | Tool-use ≤5 turns: PASS. APScheduler: PASS. Timeout: `timeout=300` (all tenants combined) vs ADR-005 example `timeout=120`; decision not documented — ARCH-5 open |

---

## Architecture Findings

### ARCH-1 [P1] — RS256 Mandated by ADR-003; HS256 Still Implemented
Symptom: JWT signing algorithm is HS256 (symmetric). No JWKS endpoint exists.
Evidence: `app/config.py:49` — `jwt_algorithm: str = "HS256"`; `docs/adr/003-rbac-design.md` §Decision — "JWT signed with RS256 (asymmetric). Public key published at `/auth/jwks.json`."
Root cause: Deferred architectural decision — HS256 shipped as a simpler v1 shortcut; key rotation requires redeploy.
Impact: No key rotation without downtime; no standard JWKS discovery; incompatible with OAuth2 / external IdP migration path in ADR-003 §Alternatives.
Phase 5 assessment: T16–T18 task definitions are not visible in any audited doc. If any Phase 5 task touches `app/middleware/auth.py`, `app/config.py` JWT fields, or adds a `/auth/token` endpoint, this decision must be resolved first. Proceed with T16 only after confirming none of T16–T18 modify auth paths; if they do, architecture decision required before those tasks begin.
Fix: (a) Accept HS256 and amend ADR-003 with rationale; (b) implement RS256 with JWKS endpoint. Either path must be recorded in a new ADR or ADR-003 amendment before auth is touched.

### ARCH-2 [P2] — ADR-002 Stale: Voyage AI / 1024-dim Not Documented
Symptom: ADR-002 specifies `text-embedding-3-small` (OpenAI, 1536-dim). Actual implementation and `data-map.md` use `voyage-3-lite` (Voyage AI, 1024-dim).
Evidence: `docs/adr/002-vector-database.md` §Decision — "embedding VECTOR(1536)… text-embedding-3-small (OpenAI)"; `docs/data-map.md` §ticket_embeddings — "VECTOR(1024) — voyage-3-lite pinned model".
Root cause: ADR-002 was not updated when embedding model changed (T13).
Impact: ADR-002 is the authoritative model decision record; mismatch creates confusion about current model and dimension, and incorrect HNSW memory estimates.
Fix: Update ADR-002 to reflect Voyage AI voyage-3-lite, 1024-dim. Update volume/memory estimates accordingly. Document rationale for model selection.

### ARCH-3 [P2] — RCAClusterer OTel Traces Missing After feat(metrics) Commit
Symptom: `feat(metrics)` commit added Prometheus metrics to RCAClusterer. OTel trace spans remain absent.
Evidence: `app/jobs/rca_clusterer.py` — imports from `prometheus_client` only; no `trace.get_tracer()` or span context; `docs/observability.md §3.2` — "Background jobs (RCA, cost aggregator) start their own root traces." Not implemented.
Resolution status: PARTIAL — Prometheus §2.5 requirements satisfied (`gdev_rca_run_duration_seconds`, `gdev_rca_tickets_scanned`, `gdev_rca_clusters_active` present and correctly labeled). OTel root trace per RCA run (observability.md §3.2) not implemented.
Root cause: OTel instrumentation omitted during T14/T15; `feat(metrics)` commit addressed metrics only.
Impact: No distributed trace linkage from `/webhook` → embedding → RCA run; no per-tenant RCA latency visibility in Grafana Tempo; violates observability.md §3.2 contract.
Fix: Add OTel tracer to RCAClusterer using the same noop-fallback pattern as `app/middleware/auth.py` lines 17–37. Instrument `run_tenant()` as root span and `_upsert_cluster()` as child span. Minimum attributes: `tenant_id_hash`, `ticket_count`, `cluster_count`.

### ARCH-4 [P2] — RCAClusterer Budget Check Bypasses CostLedger
Symptom: LLM calls in `_upsert_cluster()` are gated by a cluster count cap, not by `CostLedger.check_budget()`. Actual LLM cost not recorded per tenant.
Evidence: `app/jobs/rca_clusterer.py:164-180` — `budget_cap = max(1, min(50, int(rca_budget_per_run_usd / Decimal("0.003"))))` caps clusters before LLM calls; no import or call to `CostLedger`; `docs/observability.md §5.1` — "Every LLMClient.run_agent() call updates cost_ledger" — but `summarize_cluster()` calls `self._client.messages.create()` directly, bypassing `run_agent()` and the ledger write.
Phase 5 acceptability: DEFERRED. The cluster count cap provides a coarse cost guard; actual RCA LLM spend per run is bounded by `rca_budget_per_run_usd`. The risk is real (untracked cost not counted against daily tenant budget) but low at ≤10 tenants and small cluster counts. Acceptable as a P2 deferral into Phase 5, with the constraint that a fix must land before tenant count exceeds 5 active tenants.
Fix: Call `CostLedger.check_budget(tenant_id)` before LLM summarization per cluster; call `CostLedger.record()` after each `summarize_cluster()` call with actual token counts from the API response.

### ARCH-5 [P3] — RCA Job Timeout 300 s vs ADR-005 Example 120 s
Symptom: `run_with_timeout()` uses `timeout=300` for all tenants combined; ADR-005 documents 120 s as the example timeout.
Evidence: `app/jobs/rca_clusterer.py:120` — `asyncio.wait_for(self.run_for_all_tenants(), timeout=300)`; `docs/adr/005-orchestration-model.md` §Consequences — "`asyncio.wait_for(job(), timeout=120)`".
Root cause: 300 s may be intentional for multi-tenant combined run; no explicit decision recorded.
Impact: A runaway RCA run consuming up to 5 minutes could degrade API latency (shared event loop). Risk is bounded at ≤10 tenants but increases linearly.
Fix: Document the 300 s choice as a note in ADR-005 §Consequences. Long-term: per-tenant timeout (`asyncio.wait_for(run_tenant(tid), timeout=30)`) to prevent single-tenant pathology from blocking all others.

### ARCH-6 [P2] — Cluster Detail ticket_ids Returns Time-Window Approximation; Violates spec.md Contract
Symptom: `GET /clusters/{id}` returns ticket IDs from `ticket_embeddings` by timestamp range, not actual cluster membership.
Evidence: `app/routers/clusters.py:152-175` — `WHERE created_at >= :first_seen AND created_at <= :last_seen`; `cluster_summaries` has no `ticket_ids[]` column; `docs/spec.md §8` — `GET /clusters/{cluster_id}` described as returning "Cluster detail with member tickets."
Phase 5 acceptability: NOT ACCEPTABLE as a permanent undocumented contract. Callers cannot reliably reconstruct cluster composition — tickets from other concurrent clusters within the time window will appear as members, and members outside the window will be silently dropped.
Fix (two options): (a) Add `cluster_ticket_memberships` join table in a new Alembic migration; populate during `_upsert_cluster()` using the actual `ticket_ids` list derived from DBSCAN output. This is the architecturally correct fix and requires a schema migration. (b) Document the heuristic explicitly in the API response schema (add `ticket_ids_approximate: true` flag) and in spec.md §8. Option (b) is the minimum viable fix for Phase 5; option (a) is required before GA.

---

## FIX-6 / FIX-7 Verification (Phase 5 Gate)

| Fix | Previous Status | Current Code State | Verdict |
|-----|----------------|--------------------|---------|
| FIX-6: assert → ValueError cross-tenant guard | OPEN (META_ANALYSIS Cycle 5) | `_fetch_raw_texts_admin()` lines 400–411: `LOGGER.error(...)` + `raise ValueError(...)` — no `assert` statement present | **RESOLVED** |
| FIX-7: SET LOCAL missing in 3 session blocks | OPEN (META_ANALYSIS Cycle 5) | `_fetch_embeddings()` primary: line 215–216 ✅; `_fetch_embeddings()` ANN fallback: lines 242–243 ✅; `_deactivate_existing_clusters()`: line 271 ✅; `_upsert_cluster()`: lines 330–331 ✅ | **RESOLVED** |

Both FIX-6 and FIX-7 are resolved in the current codebase. META_ANALYSIS Cycle 5 listed them as OPEN; the code reflects fixes applied in recent commits. Phase 5 gate condition on these two fixes: **CLEARED**.

---

## Doc Patches Needed

| File | Section | Change |
|------|---------|--------|
| `docs/adr/002-vector-database.md` | §Decision | Replace `text-embedding-3-small` / `VECTOR(1536)` / "OpenAI" with `voyage-3-lite` / `VECTOR(1024)` / "Voyage AI"; update HNSW memory estimate for 1024-dim; document model selection rationale |
| `docs/adr/005-orchestration-model.md` | §Consequences | Clarify 300 s timeout rationale for multi-tenant combined run; distinguish from the 120 s per-job example; document migration path to per-tenant timeout |
| `docs/ARCHITECTURE.md` | §2.1 Component Status | Add rows for T05–T15 components: JWTMiddleware, RateLimitMiddleware, CostLedger, TenantRegistry, EmbeddingService, RCAClusterer, Cluster API router (`/clusters`, `/clusters/{id}`), Alembic migrations 0002–0004; bump doc version to v3.0 |
| `docs/ARCHITECTURE.md` | §6 (new) Background Jobs | Add section describing APScheduler registration, RCAClusterer lifecycle (timeout, per-tenant loop, admin session), and EmbeddingService fire-and-forget pattern |
| `docs/audit/META_ANALYSIS.md` | Open Findings table | Mark FIX-6 and FIX-7 as RESOLVED; update ARCH-3 status to PARTIAL (Prometheus ✅, OTel traces ✗) |

---

_When done: "ARCH_REPORT.md written. Run PROMPT_2_CODE.md."_
