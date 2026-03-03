# ADR-001: Primary Storage — PostgreSQL

**Status:** Accepted
**Date:** 2026-03-03
**Deciders:** Architecture

---

## Context

The current system uses:
- Redis: short-lived operational data (dedup, rate limits, pending approvals).
- SQLite (optional): local event log via `EventStore`.
- Google Sheets: audit log, written asynchronously via `SheetsClient`.

This setup works for a single-tenant demo, but fails for enterprise requirements:

1. Google Sheets has no real query capability. Audit analysis requires exporting CSVs.
2. SQLite is not suitable for concurrent multi-process access or horizontal scaling.
3. There is no persistent store for tickets, RBAC, or agent configs.
4. Multi-tenant isolation via row-level security requires a real RDBMS.
5. pgvector (semantic search / RCA clustering) is only available in Postgres.

The decision is: what replaces SQLite and Google Sheets as the system of record?

---

## Decision

**Use PostgreSQL (≥ 16) as the primary persistent store for all durable data.**

- Tickets, classifications, audit log, tenants, RBAC, agent configs, cost ledger, eval runs.
- pgvector extension enabled for ticket embeddings and cluster queries.
- Redis retained for its current role (TTL-based ephemeral data only).
- Google Sheets integration retained as an optional audit export (opt-in per tenant), not
  the primary audit store.
- SQLite `EventStore` retained in dev/test only; disabled in production.

---

## Alternatives Considered

### Alternative A: DynamoDB
- **Pro:** Fully managed on AWS; no operational overhead; scales horizontally.
- **Con:** No relational joins; no row-level security; no pgvector; query patterns for
  audit log and clustering are ill-suited to a key-value store. High risk of scan costs.
- **Rejected:** Relational access patterns dominate; pgvector requirement rules it out.

### Alternative B: MongoDB
- **Pro:** Flexible schema; good for semi-structured ticket metadata.
- **Con:** No pgvector; weaker ACID guarantees than Postgres; row-level security requires
  application-layer enforcement (more attack surface); less familiar to target engineers.
- **Rejected:** pgvector and ACID guarantees are non-negotiable.

### Alternative C: Neon (serverless Postgres)
- **Pro:** Postgres-compatible; zero operational overhead; scales to zero between use.
- **Con:** Cold start latency incompatible with p99 < 3 s SLA; connection pooling behavior
  differs from standard Postgres in ways that affect RLS setup.
- **Considered for future:** Viable for dev/staging environments. Not for production v1.

### Alternative D: Keep SQLite + Sheets
- **Con:** Blocks multi-tenant isolation, RBAC, and pgvector. Not viable for enterprise.
- **Rejected.**

---

## Consequences

**Positive:**
- Single system of record with full ACID guarantees.
- Row-level security provides tenant isolation at the database layer (defense in depth).
- pgvector enables semantic clustering without adding a separate vector database service.
- Rich query capability for audit, analytics, and eval.
- Well-understood operational model; extensive AWS RDS support.

**Negative / Risks:**
- Operational overhead: requires backups, failover, connection pooling (pgBouncer or RDS Proxy).
- Migration work: existing SQLite `EventStore` and Sheets `AuditLogEntry` must be replaced.
- Schema migrations must be managed (Alembic); adds deployment complexity.

**Mitigations:**
- Use AWS RDS Postgres with Multi-AZ for HA; automated backups.
- pgBouncer in front of Postgres for connection pooling (FastAPI creates many short-lived
  connections under load).
- Alembic migration files required for every schema change (enforced in Definition of Done).
