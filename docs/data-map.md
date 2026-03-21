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
| `dedup_keys` | Redis (`{tenant}:dedup:{msg_id}`) | — | 24 h TTL | Low (hash only) |
| `rate_limit_counters` | Redis (`{tenant}:ratelimit:{user}`) | — | 60 s TTL | Low |
| `approval_pending` | Redis (`{tenant}:pending:{id}`) | Postgres | Per APPROVAL_TTL | Low |
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

All keys are namespaced by `{tenant_id}` to prevent cross-tenant collision.

| Key Pattern | Type | TTL | Contents |
|---|---|---|---|
| `{tenant_id}:dedup:{message_id}` | STRING | 86400 s | `"1"` (existence flag) |
| `{tenant_id}:ratelimit:{user_id}` | ZSET | 60 s (sliding) | Request timestamps |
| `{tenant_id}:pending:{pending_id}` | STRING (JSON) | `APPROVAL_TTL_SECONDS` | Serialized `PendingDecision` |
| `tenant:{tenant_id}:config` | STRING (JSON) | 300 s | Cached `TenantConfig` JSON (`TenantRegistry`) |
| `jwt:blocklist:{jti}` | STRING | Token expiry | `"1"` (revoked flag) |
| `auth_ratelimit:{email_hash}` | STRING | 60 s | Login attempt counter. Global scope by design, so it intentionally omits a tenant prefix and rate-limits the same email hash across all tenants. |

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
| Redis (dedup, rate limit) | Per TTL | Operational; auto-expired |

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
- Medium-PII fields stored in Postgres under RLS. Not in Redis (except reviewer token, which is
  a hash).
- High-PII secrets stored encrypted at rest (AWS Secrets Manager in prod; environment variable
  in dev).
- The `user_id` received in webhooks is always hashed (SHA-256) before any persistence or log
  emission.

---

## 6. Tenant Isolation Model

**Principle**: Each tenant's data is invisible to all other tenants at every layer.

### Application layer
- `tenant_id` is resolved from the JWT on every request and injected into all service calls.
- No service method may be called without a `tenant_id`. Missing tenant = HTTP 401, request dropped.

### Database layer (Row-Level Security)

```sql
-- Applied to all tenant-scoped tables:
ALTER TABLE tickets ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON tickets
  USING (tenant_id = current_setting('app.current_tenant_id')::UUID);

-- Set at connection start:
SET app.current_tenant_id = '<tenant_id_from_jwt>';
```

- Application DB user (`gdev_app`) has no `BYPASSRLS` privilege.
- Migrations and admin operations use a separate `gdev_admin` user with `BYPASSRLS`.
- RLS is tested in integration tests: cross-tenant query must return zero rows.

### Redis layer
- Key prefix `{tenant_id}:` is enforced in all Redis client methods.
- Redis ACLs (in production): each tenant's prefix is only accessible by its own connection pool
  key (optional; depends on tenant count). Minimum: all prefixes are set by the application, not
  the caller.

### Anthropic API layer
- Single API key. Per-tenant usage is tracked in `cost_ledger`, not enforced at the API level.
- Budget guard (`CostLedger.check_budget()`) runs before each LLM call and blocks the call if
  the tenant's daily budget is exhausted.
