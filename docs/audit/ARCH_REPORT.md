---
# ARCH_REPORT — Cycle 12
_Date: 2026-03-21_

## Component Verdicts

| Component | Verdict | Note |
|-----------|---------|------|
| `app/agent.py` (AgentService) | PASS | No FastAPI imports; no HTTPException. Pure service layer. |
| `app/services/auth_service.py` (AuthService) | PASS | No FastAPI imports. Delegates to router cleanly. |
| `app/services/eval_service.py` (EvalService) | PASS | No FastAPI imports detected in service layer. |
| `app/routers/auth.py` | PASS | Thin HTTP adapter; all logic delegated to AuthService. |
| `app/routers/clusters.py` | PASS | Router contains DB queries directly (no dedicated ClusterService), but emits OTel spans and Prometheus metrics. Pattern is consistent with prior cycles; lower ARCH-9 risk than main.py. |
| `app/routers/eval.py` | PASS | Delegates to EvalService. |
| `app/main.py` (webhook + approve handlers) | DRIFT | `/webhook` and `/approve` contain business logic (tenant resolution, dedup, HMAC secret check, OTel span management) that belongs in a service layer. Pre-existing ARCH-9; not regressed in Phase 10–11. |
| `app/jobs/rca_clusterer.py` | PASS | No FastAPI imports. OTel spans present via try/except fallback. `SET LOCAL` confirmed via `_set_tenant_ctx` helper (FIX-H closed CODE-1). |
| `app/db.py` (`_set_tenant_ctx`) | PASS | Single authoritative f-string SET LOCAL helper; UUID-validated before interpolation. Contract-G satisfied. |
| `scripts/cli.py` (CLI-1) | PASS | Click-based CLI exists; covers tenant and RCA operations. No live API calls in handlers. |
| `scripts/demo.py` (PORT-3) | PASS | End-to-end demo script exists with httpx-based HTTP calls against Docker Compose stack. |
| `alembic/versions/0005_cluster_membership.py` (CLU-1/CLU-2) | PASS | `rca_cluster_members` table created with composite PK, CASCADE FKs, RLS policy (joins through `cluster_summaries.tenant_id`), and correct `gdev_app`/`gdev_admin` grants. |
| `docs/WORKFLOW.md` (PORT-2) | PASS | File exists and documents the AI development workflow. |
| README Mermaid diagram (PORT-1) | PASS | `README.md` contains a `mermaid` fenced block. |
| `docs/adr/006-mcp-server-evaluation.md` (PORT-4) | PASS | ADR exists, documents skip decision with rationale and revisit trigger. |

---

## ADR Compliance

| ADR | Verdict | Note |
|-----|---------|------|
| ADR-001 Storage: PostgreSQL + RLS + Redis cache | PASS | PostgreSQL with 16-table schema, full RLS policies, Alembic migrations, `gdev_admin`/`gdev_app` role separation. Redis retained for ephemeral data only. |
| ADR-002 Vector DB: pgvector conditional | PASS | `ticket_embeddings.embedding VECTOR(1024)` via Voyage AI; HNSW/ivfflat index; TEXT fallback when pgvector absent. `0004_resize_ticket_embeddings_vector_to_1024.py` migration confirms 1024-dim contract. |
| ADR-003 RBAC: RS256 mandated vs HS256 implemented | DRIFT | ADR-003 §JWT Structure explicitly accepts HS256 for v1. Implementation at `app/config.py:49` and `app/services/auth_service.py` is consistent with the accepted ADR. META_ANALYSIS "P1-1 open" references an earlier intent superseded by ADR-003. The finding is DRIFT (documentation ambiguity), not a code violation. Requires a clarifying note in ADR-003 and closure of P1-1 in CODEX_PROMPT. |
| ADR-004 Observability: OTel spans + Prometheus in new services | DRIFT | OTel spans and Prometheus counters/histograms present in `clusters.py` and `auth_service.py`. ARCH-5 remains open: `docs/adr/004-observability-stack.md` does not document the `/metrics` JWT exemption. Inline comment at `app/main.py:371` is the only record. |
| ADR-005 Orchestration: Claude tool_use loop ≤5 turns | PASS | `app/llm_client.py:186` confirms `max_turns: int = 5` default; loop bounded by `range(max_turns)` at line 199. APScheduler 15-minute RCA interval confirmed at `app/main.py:182–185`. |
| ADR-006 MCP Server: skip for v1 | PASS | Decision document committed. PORT-4 deliverable confirmed. |

---

## Architecture Findings

### ARCH-5 [P2] — `/metrics` JWT Exemption Undocumented in ADR-004 and ARCHITECTURE.md

Symptom: `GET /metrics` is intentionally exempt from JWT authentication to allow Prometheus scraping. The rationale is captured only in an inline comment; ADR-004 and ARCHITECTURE.md are silent.

Evidence: `app/main.py:371` — `# JWT auth is intentionally exempted for Prometheus scrapes; access is restricted at the network layer.` ADR-004 and ARCHITECTURE.md contain no mention of this exemption.

Root cause: The exemption was implemented during a fix cycle (FIX-F) but DOC-1/DOC-2 doc patches were not completed.

Impact: Security auditors reading ADR-004 or ARCHITECTURE.md find no documented policy for this auth bypass. If network-layer restrictions are relaxed, there is no referenced policy to enforce.

Fix: Add a note to `docs/adr/004-observability-stack.md` under §Instrumentation Scope: "`GET /metrics` is exempt from JWT middleware. Prometheus uses a pull model; the endpoint must be reachable without a bearer token. Mitigation: restrict at the network layer (Docker network policy / VPC security group)." Add a corresponding note to ARCHITECTURE.md §Middleware Stack or §Security.

---

### ARCH-6 [P2] — CLU-1 Timestamp Heuristic Replaced: CONFIRMED CLOSED

Symptom: META_ANALYSIS listed ARCH-6 as open pending code verification that `GET /clusters/{cluster_id}` returns tickets from persisted membership rather than a timestamp heuristic.

Evidence: `app/routers/clusters.py:203–220` — `get_cluster()` queries `SELECT ticket_id FROM rca_cluster_members WHERE cluster_id = :cluster_id ORDER BY created_at DESC, ticket_id DESC LIMIT 10`. No timestamp heuristic present. `app/routers/clusters.py:228–342` — `GET /clusters/{cluster_id}/tickets` joins `rca_cluster_members` with `tickets` using pagination. `alembic/versions/0005_cluster_membership.py` — migration creates `rca_cluster_members` with composite PK, RLS, and grants.

Root cause: CLU-1 was fully implemented. The discrepancy was between `tasks.md` (marked done) and the CODEX_PROMPT finding table (still listed as open).

Impact: None — implementation is correct. Close ARCH-6 and update CODEX_PROMPT.

Fix: Close ARCH-6 in CODEX_PROMPT open findings table. No code change required.

---

### ARCH-9 [P2] — Business Logic Embedded in `/webhook` and `/approve` in `app/main.py`

Symptom: The `/webhook` and `/approve` route handlers contain orchestration logic that violates the router-as-thin-adapter principle established by SVC-1/SVC-2.

Evidence: `app/main.py:255–347` (`webhook()`) — tenant UUID resolution from JWT vs payload, dedup cache read/write, payload mutation via `model_copy`, OTel span lifecycle management, and HTTPException raising for tenant validation. `app/main.py:349–366` (`approve()`) — inline HMAC `compare_digest` against `APPROVE_SECRET`, JWT tenant extraction from `request.state`, and direct call to `app.state.agent.approve()`.

Root cause: These endpoints pre-date the SVC-1/SVC-2 extraction pattern applied to auth and eval in Phase 9. They were explicitly deferred (noted in prior cycles as ARCH-9).

Impact: Webhook orchestration logic cannot be unit-tested without a full FastAPI test client. As webhook logic grows, defects become harder to isolate. The HMAC check in `/approve` is particularly risky as an inline implementation with no service-layer test coverage.

Fix: Define as Phase 12 task `SVC-4`: extract webhook orchestration into `WebhookService` (tenant resolution, dedup, payload validation) and approval orchestration into `ApprovalService` (HMAC check, tenant guard, dispatch). Routers become pure HTTP adapters. HTTPException usage stays in the router layer; service methods return result objects or raise domain exceptions. Estimated scope: 2–3 days. Pattern mirrors SVC-1 (AuthService) and SVC-2 (EvalService).

---

### ARCH-10 [P2] — `auth_ratelimit:{email_hash}` Redis Key Absent from data-map §3

Symptom: The rate-limit Redis key used for login attempt throttling is not documented in the data-map Redis Key Schema.

Evidence: `app/middleware/rate_limit.py:129` — `auth_key = f"auth_ratelimit:{email_hash}"`. `docs/data-map.md` §3 — five key patterns listed; `auth_ratelimit:{email_hash}` is absent. The key intentionally has no tenant prefix (global email-based rate limit).

Root cause: Key was implemented without a corresponding data-map update. Carried forward as CODE-4/CODE-8 across Cycles 8–11.

Impact: Operators enumerating Redis key space from data-map will miss this key. Redis ACL design for production cannot be correctly specified without a complete key inventory.

Fix: Add to `docs/data-map.md` §3: `auth_ratelimit:{email_hash}` / STRING / 60 s / Login attempt counter (global — intentionally no tenant prefix; rate-limits by email hash across all tenants).

---

### ARCH-11 [P3] — Phase 10–11 Deliverables Not Reflected in ARCHITECTURE.md §2.1 and §2.2

Symptom: ARCHITECTURE.md component status table (§2.1) and repository layout (§2.2) do not include `scripts/cli.py`, `scripts/demo.py`, `docs/WORKFLOW.md`, or `docs/adr/006-mcp-server-evaluation.md`.

Evidence: `docs/ARCHITECTURE.md:82–141` — `scripts/` directory absent from layout tree; `docs/WORKFLOW.md` and `docs/adr/006-*` not listed. All four files confirmed to exist on disk.

Root cause: ARCHITECTURE.md was not updated when Phase 10 (CLI-1) and Phase 11 (PORT-1–PORT-4) deliverables were committed.

Impact: Low — informational only. Engineers reading ARCHITECTURE.md to understand project structure will not discover the CLI or demo script.

Fix: See Doc Patches Needed table below.

---

### ARCH-12 [P2] — ADR-003 RS256 vs HS256 Ambiguity Requires Explicit Closure

Symptom: META_ANALYSIS Cycle 12 carries "P1-1 open — RS256 mandated, HS256 implemented." The accepted ADR-003 explicitly documents HS256 as the v1 choice. Neither spec.md §5.2 nor any other authoritative document mandates RS256 for v1.

Evidence: `docs/adr/003-rbac-design.md:53` — "JWT signed with HS256 (symmetric shared secret, v1 simplification)." `app/config.py:49` — `jwt_algorithm: str = "HS256"`. `docs/spec.md` §5 — JWT requirement stated; no algorithm specified.

Root cause: P1-1 appears to be a carry-forward from a pre-ADR-003 era where RS256 was under consideration. ADR-003 superseded that intent but the finding was never formally closed in CODEX_PROMPT.

Impact: Tracking a phantom violation wastes review bandwidth. More importantly, if P1-1 is treated as live, it could trigger a premature RS256 migration that adds JWKS infrastructure not needed for v1.

Fix: Add a note to ADR-003 §Consequences: "RS256 with a JWKS endpoint is deferred to v2 (when an external IdP or public key distribution becomes necessary). HS256 is the accepted v1 algorithm per this ADR. Finding P1-1 in CODEX_PROMPT is superseded by this decision." Close P1-1 in CODEX_PROMPT.

---

### ARCH-13 [P2] — SET LOCAL f-string Interpolation: Contract-G Satisfied but Requires Ongoing Vigilance

Symptom: The `_set_tenant_ctx()` helper in `app/db.py:25` uses an f-string with UUID validation to construct the `SET LOCAL` statement. This correctly satisfies Contract-G (asyncpg rejects parameterized SET LOCAL). However, if any new Phase 10–11 call site bypasses `_set_tenant_ctx()` and introduces a parameterized form, it would silently regress (asyncpg error surfaces only under PG).

Evidence: `app/db.py:25` — `text(f"SET LOCAL app.current_tenant_id = '{UUID(str(tenant_id))}'")`. Grep of Phase 10–11 scope shows only one `SET LOCAL` site in the codebase, all routed through `_set_tenant_ctx`. No new parameterized SET sites detected in Phase 10–11 files.

Root cause: Not a current violation. Noted as a vigilance item given the history of this pattern (CODE-1 / REG-2 in Cycle 11).

Impact: Low for current HEAD. Regression risk exists if future engineers add DB session blocks without using `_set_tenant_ctx()`.

Fix: No code change needed. Consider adding a CI grep check: `grep -rn "SET LOCAL" app/ | grep -v "_set_tenant_ctx"` to catch any future bypass.

---

## Doc Patches Needed

| File | Section | Change |
|------|---------|--------|
| `docs/adr/004-observability-stack.md` | §Instrumentation Scope or new §Security Note | Add: "`GET /metrics` is exempt from JWT middleware. Prometheus pull model requires unauthenticated access. Mitigation: restrict at network layer (Docker bridge / VPC security group)." |
| `docs/ARCHITECTURE.md` | §2.2 Repository Layout | Add `scripts/` subtree with `cli.py`, `demo.py`, `seed_db.py`; add `docs/WORKFLOW.md` to docs listing; add `docs/adr/006-mcp-server-evaluation.md` to adr listing. |
| `docs/ARCHITECTURE.md` | §2.1 Component Status | Add rows: `scripts/cli.py` (CLI-1, Phase 10 ✅), `scripts/demo.py` (PORT-3, Phase 11 ✅), `docs/WORKFLOW.md` (PORT-2, Phase 11 ✅), `docs/adr/006-mcp-server-evaluation.md` (PORT-4, Phase 11 ✅). |
| `docs/data-map.md` | §3 Redis Key Schema | Add row: `auth_ratelimit:{email_hash}` / STRING / 60 s / Login attempt counter (global, no tenant prefix — intentional design). |
| `docs/adr/003-rbac-design.md` | §Consequences | Add: "RS256 with JWKS endpoint deferred to v2. HS256 is the accepted v1 algorithm. Finding P1-1 in CODEX_PROMPT is superseded by this decision." |
| `docs/CODEX_PROMPT.md` | Open findings table | Close ARCH-6 (CLU-1 heuristic replaced, confirmed in code). Close P1-1 (RS256 vs HS256 — ADR-003 accepts HS256 for v1). |

---
