# Data Map v1.0

_Date: 2026-03-03 · All schema changes require a migration file and a bump to this document._

---

## 1. Entity List and Storage Locations

| Entity | Primary Store | Secondary | Retention | PII Class |
|---|---|---|---|---|
| `tenants` | Postgres | Redis cache (TTL 5 min) | Indefinite | Low |
| `tenant_users` | Postgres | — | Indefinite | Medium (email, name) |
| `api_keys` | Postgres (hashed) | — | Indefinite | High (key value) |
| `webhook_secrets` | Postgres (encrypted) | — | Indefinite | High |
| `tickets` | Postgres | — | 2 years | High (player message text) |
| `ticket_classifications` | Postgres | — | 2 years | Low |
| `ticket_extracted_fields` | Postgres | — | 2 years | Medium (transaction_id, username) |
| `proposed_actions` | Postgres | — | 2 years | Low |
| `pending_decisions` | Redis (TTL) + Postgres | — | Redis: per TTL; Postgres: 2 years | Medium |
| `approval_events` | Postgres | — | 5 years | Medium (reviewer identity) |
| `audit_log` | Postgres | — | 5 years | Medium (hashed user_id) |
| `ticket_embeddings` | Postgres (pgvector) | — | 2 years (mirrors ticket retention) | Low (vector only) |
| `cluster_summaries` | Postgres | — | 6 months (rolling) | Low |
| `agent_configs` | Postgres | Redis cache (TTL 60 s) | Indefinite (versioned) | Low |
| `cost_ledger` | Postgres | — | 2 years | Low |
| `eval_runs` | Postgres | — | 1 year | Low |
| `eval_cases` | File (`eval/cases.jsonl`) | — | Version-controlled | Medium (synthetic) |
| `triage_exemplars` | File (`eval/exemplars/triage_v1.jsonl`) | — | Version-controlled | Medium (synthetic) |
| `dedup_cache` | Redis (`{tenant}:dedup:{msg_id}`) | — | 24 h TTL | Medium (serialized webhook response) |
| `rate_limit_counters` | Redis (`{tenant}:ratelimit:{user_hash}`) | — | 60 s / 10 s TTL | Low |
| `approval_pending` | Redis (`{tenant}:pending:{id}`) | Postgres | Per APPROVAL_TTL | Medium (serialized pending decision) |
| `session_tokens` | Redis (JWT blocklist) | — | Token expiry | High |

---

## 2. Postgres Schema (Key Tables)

### `tenants`
```sql
tenant_id       UUID PRIMARY KEY DEFAULT gen_random_uuid()
name            TEXT NOT NULL
slug            TEXT UNIQUE NOT NULL          -- URL-safe identifier
plan            TEXT DEFAULT 'standard'       -- standard | enterprise
daily_budget_usd DECIMAL(10,4) DEFAULT 10.0
approval_ttl_s  INTEGER DEFAULT 3600
auto_approve_threshold DECIMAL(4,3) DEFAULT 0.85
approval_categories TEXT[] DEFAULT '{billing}'
url_allowlist   TEXT[] DEFAULT '{}'
is_active       BOOLEAN DEFAULT TRUE
created_at      TIMESTAMPTZ DEFAULT NOW()
updated_at      TIMESTAMPTZ DEFAULT NOW()
```

### `tenant_users`
```sql
user_id         UUID PRIMARY KEY DEFAULT gen_random_uuid()
tenant_id       UUID REFERENCES tenants(tenant_id)
email           TEXT NOT NULL                 -- PII: stored, not logged
email_hash      TEXT NOT NULL                 -- used in audit logs
display_name    TEXT
role            TEXT NOT NULL                 -- tenant_admin | support_agent | viewer
is_active       BOOLEAN DEFAULT TRUE
created_at      TIMESTAMPTZ DEFAULT NOW()
```

### `tickets`
```sql
ticket_id       UUID PRIMARY KEY DEFAULT gen_random_uuid()
tenant_id       UUID REFERENCES tenants(tenant_id)
message_id      TEXT                          -- external idempotency key
user_id_hash    TEXT NOT NULL                 -- SHA-256 of original user_id
raw_text        TEXT NOT NULL                 -- PII-bearing; RLS enforced
platform        TEXT
game_title      TEXT
created_at      TIMESTAMPTZ DEFAULT NOW()
```

### `ticket_classifications`
```sql
classification_id UUID PRIMARY KEY DEFAULT gen_random_uuid()
ticket_id       UUID REFERENCES tickets(ticket_id)
tenant_id       UUID REFERENCES tenants(tenant_id)
category        TEXT NOT NULL
urgency         TEXT NOT NULL
confidence      DECIMAL(4,3) NOT NULL
agent_config_id UUID REFERENCES agent_configs(agent_config_id)
created_at      TIMESTAMPTZ DEFAULT NOW()
```

### `audit_log`
```sql
audit_id        UUID PRIMARY KEY DEFAULT gen_random_uuid()
tenant_id       UUID REFERENCES tenants(tenant_id)
request_id      TEXT
message_id      TEXT
user_id_hash    TEXT
category        TEXT
urgency         TEXT
confidence      DECIMAL(4,3)
action_tool     TEXT
status          TEXT                          -- executed | pending | approved | rejected
approved_by     TEXT                          -- 'auto' or SHA-256[:16] hash of reviewer identity
ticket_id       UUID
latency_ms      INTEGER
input_tokens    INTEGER
output_tokens   INTEGER
cost_usd        DECIMAL(10,6)
created_at      TIMESTAMPTZ DEFAULT NOW()
```

### `ticket_embeddings`
```sql
embedding_id    UUID PRIMARY KEY DEFAULT gen_random_uuid()
ticket_id       UUID REFERENCES tickets(ticket_id)
tenant_id       UUID REFERENCES tenants(tenant_id)
embedding       VECTOR(1024)                  -- voyage-3-lite pinned model
model_version   TEXT NOT NULL
created_at      TIMESTAMPTZ DEFAULT NOW()
-- INDEX: ivfflat or hnsw on embedding for ANN queries

Model migration path:
1. Deploy migration that changes vector size.
2. Backfill all existing rows in `ticket_embeddings` with the new model.
3. Only then switch `embedding_model` in runtime config.
```

### `cluster_summaries`
```sql
cluster_id      UUID PRIMARY KEY DEFAULT gen_random_uuid()
tenant_id       UUID REFERENCES tenants(tenant_id)
label           TEXT NOT NULL                 -- LLM-generated short label
summary         TEXT NOT NULL                 -- LLM-generated summary
ticket_count    INTEGER NOT NULL
severity        TEXT                          -- low | medium | high
first_seen      TIMESTAMPTZ
last_seen       TIMESTAMPTZ
is_active       BOOLEAN DEFAULT TRUE
updated_at      TIMESTAMPTZ DEFAULT NOW()
```

### `agent_configs`
```sql
agent_config_id UUID PRIMARY KEY DEFAULT gen_random_uuid()
tenant_id       UUID REFERENCES tenants(tenant_id)
agent_name      TEXT NOT NULL
version         INTEGER NOT NULL DEFAULT 1
model_id        TEXT NOT NULL
max_turns       INTEGER DEFAULT 5
tools_enabled   TEXT[] NOT NULL
guardrails      JSONB NOT NULL DEFAULT '{}'
prompt_version  TEXT NOT NULL
is_current      BOOLEAN DEFAULT TRUE
created_at      TIMESTAMPTZ DEFAULT NOW()
```

### `cost_ledger`
```sql
ledger_id       UUID PRIMARY KEY DEFAULT gen_random_uuid()
tenant_id       UUID REFERENCES tenants(tenant_id)
date            DATE NOT NULL
input_tokens    BIGINT DEFAULT 0
output_tokens   BIGINT DEFAULT 0
cost_usd        DECIMAL(10,4) DEFAULT 0
request_count   INTEGER DEFAULT 0
UNIQUE(tenant_id, date)
```

---

## 3. Redis Key Schema

Tenant-scoped operational keys are namespaced by `{tenant_id}` to prevent
cross-tenant collision. Global security keys are listed explicitly as
exceptions.

| Key Pattern | Type | TTL | Contents |
|---|---|---|---|
| `{tenant_id}:dedup:{message_id}` | STRING | 86400 s | Serialized `WebhookResponse` used for idempotent replay. May include pending metadata, action payloads, draft response text, and hashed user identifiers. |
| `{tenant_id}:ratelimit:{user_id_hash}` | STRING counter | 60 s | Per-minute webhook count keyed by SHA-256 user hash. |
| `{tenant_id}:ratelimit_burst:{user_id_hash}` | STRING counter | 10 s | Short-window burst count keyed by SHA-256 user hash. |
| `{tenant_id}:pending:{pending_id}` | STRING (JSON) | `APPROVAL_TTL_SECONDS` | Serialized `PendingDecision` |
| `tenant:{tenant_id}:config` | STRING (JSON) | 300 s | Cached `TenantConfig` JSON (`TenantRegistry`) |
| `jwt:blocklist:{jti}` | STRING | Token expiry | Revoked-token flag. Global by design because JTI values are token-scoped and must remain invalid across all tenants. |
| `auth_ratelimit:{email_hash}` | STRING | 60 s | Login attempt counter. Global by design, so it intentionally omits a tenant prefix and rate-limits the same email hash across all tenants. |

---

## 4. Retention Policy

| Category | Retention | Justification |
|---|---|---|
| Raw ticket text | 2 years | GDPR Article 5(1)(e) storage limitation; game studio support SLA |
| Audit log | 5 years | Financial dispute resolution; regulatory compliance |
| Approval events | 5 years | Audit trail for HITL decisions |
| Embeddings | 2 years | Mirror ticket retention; no independent PII |
| Cluster summaries | 6 months rolling | Operational analytics; no long-term value |
| Cost ledger | 2 years | Billing reconciliation |
| Eval runs | 1 year | Trend analysis; ML governance |
| Redis (dedup, pending approval, rate limit) | Per TTL | Operational; auto-expired |

Deletion is logical (soft delete with `deleted_at` column) for tickets and users; physical deletion
for Redis entries (TTL). GDPR right-to-erasure: `raw_text` overwritten with `[ERASED]`, all other
fields retained for audit integrity.

---

## 5. PII Classification

| PII Level | Definition | Examples in this system |
|---|---|---|
| **High** | Directly identifies a person or grants access | `raw_text` (may contain name/email), API keys, JWT tokens, webhook secrets |
| **Medium** | Indirectly identifies a person or links records | `email`, `display_name`, `transaction_id`, `reported_username`, `reviewer` identity |
| **Low** | No personal link; operational data | Category, urgency, confidence, latency, token counts, cluster labels |

**Storage rules:**
- High-PII fields are never written to logs. Logs use hashed variants or omit entirely.
- Medium-PII fields are stored in Postgres under RLS by default. Redis Medium-PII exceptions are
  explicit and TTL-bound: dedup response caches (`{tenant_id}:dedup:{message_id}`) and pending
  approvals (`{tenant_id}:pending:{pending_id}`) are tenant-namespaced operational records.
- High-PII secrets stored encrypted at rest (AWS Secrets Manager in prod; environment variable
  in dev).
- The `user_id` received in webhooks is always hashed (SHA-256) before any persistence or log
  emission.

---

## 6. Tenant Isolation Model

**Principle**: Each tenant's data is invisible to all other tenants at every layer.

### Application layer
- Protected read/admin/approval APIs resolve `tenant_id`, user, role, and JTI
  from JWT middleware and inject that context into route dependencies and
  service calls.
- `POST /webhook` is JWT-exempt by design. Its tenant context is resolved from
  signed `X-Tenant-Slug` plus `X-Webhook-Signature` in
  `app/middleware/signature.py` before the webhook service runs.
- Missing tenant context is rejected for tenant-scoped service calls. Protected
  JWT APIs return HTTP 401 on missing/invalid JWT; webhook calls return 400/401
  on missing slug or invalid signature.

### Database layer (Row-Level Security)

```sql
-- Applied to all tenant-scoped tables:
ALTER TABLE tickets ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON tickets
  USING (tenant_id = current_setting('app.current_tenant_id', TRUE)::UUID);

-- Set inside the current transaction only:
SELECT set_config('app.current_tenant_id', '<tenant_id_from_jwt>', TRUE);
```

- Application DB user (`gdev_app`) has no `BYPASSRLS` privilege.
- Migrations and admin operations use a separate `gdev_admin` user with `BYPASSRLS`.
- Runtime code sets tenant context through `app/db.py::_set_tenant_ctx()` inside
  `session.begin()`. The third `TRUE` argument to `set_config()` makes the
  value transaction-local, equivalent to `SET LOCAL`, so tenant context is not
  retained on a reused connection.
- RLS is tested in integration tests: cross-tenant query must return zero rows
  and cross-tenant writes by `gdev_app` must fail.

### Redis layer
- Key prefix `{tenant_id}:` is enforced in all Redis client methods.
- Redis ACLs (in production): each tenant's prefix is only accessible by its own connection pool
  key (optional; depends on tenant count). Minimum: all prefixes are set by the application, not
  the caller.

### Anthropic API layer
- Single API key. Per-tenant usage is tracked in `cost_ledger`, not enforced at the API level.
- Budget guard (`CostLedger.check_budget()`) runs before each LLM call and blocks the call if
  the tenant's daily budget is exhausted.
