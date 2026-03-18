# ADR-002: Vector Database — pgvector (Embedded in PostgreSQL)

**Status:** Accepted
**Date:** 2026-03-03
**Deciders:** Architecture

---

## Context

The Root Cause Analyzer requires semantic similarity search over recent ticket embeddings.
Specifically, it must:

1. Store a vector embedding (1024 dimensions) for each ingested ticket.
2. Query the N most similar embeddings within a time window (approximate nearest neighbor).
3. Feed the results into a clustering algorithm (DBSCAN) to surface emerging issue patterns.

This requires a vector-capable store. The question is whether to add a standalone vector
database service or embed vector capability into an existing store.

**Volume estimates:**
- 10 tenants × 500 tickets/day = 5,000 vectors/day.
- 2-year retention = ≈3.65 million vectors.
- ANN query target: top-200 from last 24 h (≤ 12,000 candidate rows per tenant per query).

---

## Decision

**Use pgvector, the Postgres extension, as the vector store.**

- Embeddings stored in `ticket_embeddings.embedding VECTOR(1024)` when pgvector is available,
  with a `TEXT` fallback in environments that do not have the extension installed.
- Index: `HNSW` (hierarchical navigable small world) for approximate nearest neighbor.
  `ivfflat` is acceptable for smaller tenants; HNSW preferred at scale.
- Clustering logic runs in Python (scikit-learn DBSCAN) on the returned vectors.
- Embedding model: Voyage AI (`voyage-3-lite` by default in config; 1024 dimensions in the
  implemented stack) via `app/embedding_service.py`.

**Supersedes original OpenAI choice:** the initial ADR draft referenced
`text-embedding-3-small` at 1536 dimensions. T13 implemented the Voyage AI stack instead because
it delivered the target embedding quality at lower operating cost and aligned the codepath,
configuration, and stored vector size around a single 1024-dim contract.

---

## Alternatives Considered

### Alternative A: Pinecone (managed vector DB)
- **Pro:** Best-in-class ANN performance; no infrastructure to manage; namespace-based
  multi-tenant isolation.
- **Con:** Additional managed service adds operational dependency, cost (~$70/month starter),
  and vendor lock-in. At 3.65 M vectors, well within pgvector's capable range. Adds complexity
  for a solo engineer to operate.
- **Rejected:** Premature optimization. pgvector is sufficient for projected scale.

### Alternative B: Qdrant (self-hosted)
- **Pro:** Purpose-built for vectors; excellent filtering; Rust-based, fast.
- **Con:** Another service to run and monitor. Docker Compose already has Redis + Postgres;
  adding Qdrant increases operational surface. Multi-tenant isolation requires manual namespace
  handling (Qdrant collections per tenant or filter fields).
- **Rejected for v1.** Revisit if pgvector query latency exceeds 500 ms at scale.

### Alternative C: Weaviate
- **Pro:** GraphQL API; built-in vectorization.
- **Con:** High resource footprint; complex setup; overkill for this workload.
- **Rejected.**

### Alternative D: ChromaDB (in-process)
- **Pro:** Zero external service; Python-native; simple API.
- **Con:** No true multi-tenant isolation; no ACID; cannot run in distributed mode; HNSW
  index rebuilds are blocking; not production-grade.
- **Rejected for production.**

---

## Consequences

**Positive:**
- No additional service to operate. Postgres is already in the stack (per ADR-001).
- Tenant isolation via Postgres RLS applies automatically to embeddings too.
- HNSW index in pgvector achieves sub-100 ms ANN for our projected data volumes.
- Single backup strategy covers both relational and vector data.
- Schema simplicity: `ticket_embeddings` is a plain table with a vector column.
- Voyage AI reduces per-embedding cost versus the superseded OpenAI option while keeping the
  integration surface simple.

**Negative / Risks:**
- pgvector HNSW index rebuild is expensive on large tables; plan index creation with
  `CREATE INDEX CONCURRENTLY`.
- Memory footprint: HNSW index for 3.65 M × 1024-dim vectors requires significant RAM
  on the Postgres server. Mitigate with `USING hnsw (embedding vector_cosine_ops)
  WITH (m=16, ef_construction=64)` (conservative settings).
- Embedding model API cost remains an external dependency and should be re-evaluated if traffic
  or vendor pricing changes materially.

**Review trigger:** If p99 ANN query latency exceeds 500 ms with real tenant data, evaluate
migrating to Qdrant or Pinecone with a data export step.
