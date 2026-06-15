# Deployment Readiness Notes

These notes describe local and production-like setup knowledge. They do not
claim that this repository is production ready, externally
deployed, or operating live tenants.

## Readiness Scope

What this proof covers:

- Local Docker Compose dependencies, health checks, and migration verification.
- Required vs optional environment variables for a production-like local run.
- Backup and restore commands for Postgres state.
- Redis state classification and recovery guidance.
- Known limitations that would need work before production readiness.

What this proof does not cover:

- Cloud networking, TLS termination, WAF rules, VPC/firewall controls, managed
  Redis ACLs, managed database backups, incident response staffing, or real
  tenant operations.
- Provider-side per-tenant LLM credentials. Tenant spend is controlled locally
  through `cost_ledger`.
- A production SLA. Current SLOs and load evidence are local operating targets.

## Secrets Checklist

| Variable | Required | Purpose | Local review value |
|----------|----------|---------|--------------------|
| `DATABASE_URL` | Required outside Compose | Async Postgres URL for app and CLI migration checks | Compose injects `postgresql+asyncpg://...@postgres:5432/gdev` |
| `REDIS_URL` | Required outside Compose | Redis for dedup, approvals, rate limits, JWT blocklist, tenant config cache | Compose injects `redis://redis:6379` |
| `JWT_SECRET` | Required | Signs HS256 JWTs for protected REST APIs | Use a 32+ byte random value outside demo |
| `WEBHOOK_SECRET_ENCRYPTION_KEY` | Required for signed webhooks | Fernet key used to decrypt per-tenant webhook HMAC secrets from Postgres | Compose uses a committed demo key only for local fixtures |
| `APPROVE_SECRET` | Recommended | Optional approval endpoint defense in depth in addition to JWT role checks | `approve-secret` in demo fixtures |
| `ANTHROPIC_API_KEY` | Required for `LLM_MODE=live` | Live provider calls | Empty for deterministic `LLM_MODE=demo` |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_APPROVAL_CHAT_ID` | Optional | Approval notifications | Empty unless testing Telegram |
| `GOOGLE_SHEETS_CREDENTIALS_JSON` / `GOOGLE_SHEETS_ID` | Optional | External audit export | Empty for local proof |
| `OTLP_ENDPOINT` | Optional | Trace export | Compose points to local Tempo |

Never commit real provider keys, bot tokens, approval secrets, JWT secrets, or
webhook encryption keys. Rotate local demo values before any shared
environment that is reachable by other people.

## Local Production-Like Config Example

Use this shape for a local run that is closer to a real deployment while still
remaining non-production:

```bash
APP_ENV=staging-like
LLM_MODE=demo
DATABASE_URL=postgresql+asyncpg://gdev_app:change-me@postgres:5432/gdev
REDIS_URL=redis://redis:6379
JWT_SECRET=$(openssl rand -hex 32)
WEBHOOK_SECRET_ENCRYPTION_KEY=$(python - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
)
APPROVE_SECRET=$(openssl rand -hex 24)
OTLP_ENDPOINT=http://tempo:4318/v1/traces
```

For live LLM testing, set `LLM_MODE=live`, provide `ANTHROPIC_API_KEY`, and
keep tenant `daily_budget_usd` low. Live mode can spend real money.

## Migration And Health Smoke Path

The Compose `migrate` service runs:

```bash
alembic upgrade head
python scripts/cli.py migrations check
python scripts/seed_db.py
```

Manual verification against a running local stack:

```bash
docker compose exec agent python scripts/cli.py migrations check
curl -i http://localhost:8000/health
```

`GET /health` is application liveness only. Compose readiness additionally
depends on Postgres and Redis health checks plus successful migration
verification and seed data.

## Backup And Restore Notes

### Postgres

Back up the local Compose database:

```bash
mkdir -p ./backups
docker compose exec -T postgres pg_dump -U gdev_app -d gdev \
  --format=custom --file=/tmp/gdev.dump
docker compose cp postgres:/tmp/gdev.dump ./backups/gdev.dump
```

Restore into a fresh local database:

```bash
docker compose cp ./backups/gdev.dump postgres:/tmp/gdev.dump
docker compose exec -T postgres pg_restore -U gdev_app -d gdev \
  --clean --if-exists /tmp/gdev.dump
docker compose exec agent python scripts/cli.py migrations check
```

Production would need managed backups, point-in-time recovery, encryption,
restore drills, retention policy, and access controls. Those are not proven by
this repository.

### Redis

Redis stores ephemeral coordination state:

- Dedup cache: `{tenant_id}:dedup:{message_id}`.
- Pending approvals: `{tenant_id}:pending:{pending_id}`.
- Rate-limit counters.
- JWT blocklist entries.
- Tenant config cache.

For local recovery, prefer restarting Redis and letting TTL state rebuild. If a
pending approval is lost, re-run the webhook to create a fresh pending decision
rather than manually recreating Redis keys. Production would need an explicit
decision on Redis persistence, ACLs, encryption, and whether pending approvals
should be restored or invalidated after outage.

## Known Limitations

- The stack is local/pilot evidence, not production readiness.
- Compose secrets are visible to local Docker users and are not a secret manager.
- `/metrics` is JWT-exempt for Prometheus and must be network-restricted in a
  real deployment.
- `GET /health` does not check downstream dependencies.
- Redis isolation is key namespace isolation, not per-tenant Redis ACLs.
- There is no external deployment, live tenant traffic, production backup
  policy, or restore drill evidence.
- Read API service extraction remains open architecture debt.
