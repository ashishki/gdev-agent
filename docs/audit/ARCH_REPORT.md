# ARCH_REPORT — Cycle 15
_Date: 2026-06-12_

## Component Verdicts

| Component | Verdict | Note |
|-----------|---------|------|
| Approval TTL expiry | PASS | Expired pending approvals return 404, log `pending_expired`, and do not execute actions. |
| Cross-tenant approval boundary | PASS | Wrong-tenant approval attempts miss the tenant-scoped Redis key before execution and leave original pending state intact. |
| Rate-limit exceedance | PASS | HTTP 429 is returned before downstream handler/model work. |
| Budget exceedance | PASS | Budget exhaustion returns 429 before LLM calls and preserves tenant-scoped cost evidence. |
| Tenant isolation documentation | PASS | `docs/TENANT_ISOLATION.md` maps RLS, Redis, approval, budget, and rate-limit proof. |
| Runtime dependency guardrails | PASS | Tenant context SQL is parameterized; Redis startup ping uses `redis.asyncio` in async lifespan. |

## ADR Compliance

| ADR | Verdict | Note |
|-----|---------|------|
| ADR-001 Storage | PASS | Postgres remains primary system of record; tenant context remains transaction-local. |
| ADR-002 Vector DB | PASS | No vector-store changes. |
| ADR-003 RBAC | PASS | Approval boundary proof reinforces tenant-scoped access; no route auth changes. |
| ADR-004 Observability | PASS | Boundary tests assert log/metric signals where implemented. |
| ADR-005 Orchestration | PASS | No new scheduler or orchestration behavior. |
| ADR-006 MCP | PASS | No assistant-facing protocol surface changes. |

## Architecture Findings

None.

## Doc Patches Needed

| File | Section | Change |
|------|---------|--------|
| `docs/ARCHITECTURE.md` | Eval subsystem | Carry-forward `ARCH-HARDEN-1`: update old 25-case/basic-metric language. |
