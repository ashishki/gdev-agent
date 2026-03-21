# gdev-agent

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white) ![FastAPI](https://img.shields.io/badge/fastapi-api-009688?logo=fastapi&logoColor=white) ![Postgres](https://img.shields.io/badge/postgres-pgvector-4169E1?logo=postgresql&logoColor=white) ![Docker Compose](https://img.shields.io/badge/docker-compose-2496ED?logo=docker&logoColor=white) ![215 tests](https://img.shields.io/badge/tests-215%20passing-brightgreen)

`gdev-agent` is a multi-tenant AI triage service for game-studio player support: it receives support webhooks, blocks unsafe input before any model call, classifies and extracts structured data with an LLM, routes risky actions into human approval, and records the resulting audit, cost, and analytics trail behind one HTTP API.

## Why This Project Exists

Game studios deal with billing disputes, account-access incidents, bug reports, moderation signals, and repetitive gameplay questions at a volume where manual triage becomes slow and brittle. `gdev-agent` is the orchestration layer between inbound support traffic and downstream systems: it keeps routine requests moving, forces human review when confidence or risk is low, and preserves tenant isolation, observability, and cost controls.

## Architecture

```mermaid
flowchart LR
    caller[Webhook caller\nTelegram / n8n / Make / HTTP client] --> webhook[POST /webhook]
    webhook --> sig[Signature + rate-limit middleware]
    sig --> guard[Input guard\nlength and injection checks]
    guard --> llm[LLM tool loop\nclassify + extract + draft]
    llm --> policy[Policy + output guard\nrisk, confidence, secret and URL checks]
    policy --> decision{Risky action?}
    decision -->|Yes| pending[Store pending approval\nRedis + reviewer callback]
    pending --> approve[POST /approve]
    approve --> execute[Execute approved action\nticket + reply + audit]
    decision -->|No| execute
    execute --> result[HTTP response + audit trail\nlogs, metrics, cost ledger]
```

The current stack includes FastAPI, Redis, PostgreSQL with Row-Level Security, pgvector-backed embeddings, a clean service layer (WebhookService, ApprovalService, AuthService, EvalService), RCA clustering jobs, and an n8n integration path for orchestration and approvals. Architecture detail lives in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Feature Snapshot

| Area | What ships today |
| --- | --- |
| Ingress | `POST /webhook` entrypoint with `WebhookService` (tenant resolution, dedup, OTel tracing); per-tenant HMAC verification, rate limiting |
| AI pipeline | Claude `tool_use` classification and extraction, guarded draft generation, configurable auto-approve threshold |
| Safety | Input injection guard, output secret scan, URL allowlist enforcement, approval workflow with `ApprovalService` (HMAC + cross-tenant enforcement) |
| Execution | Tool registry for ticketing and reply actions, dedup cache for idempotent replays, pending approval storage with TTL |
| Multi-tenancy | PostgreSQL RLS on all tables (Alembic migrations), tenant registry, per-tenant encrypted secrets |
| Operations | Cost ledger with daily budget enforcement, structured JSON logs, Prometheus metrics (OTel child spans on all endpoints), Grafana/Loki/Tempo stack |
| Analytics | Eval runner with budget check, eval API, RCA clustering job (DBSCAN + pgvector), cluster read endpoints with DB-backed membership |
| Admin | `gdev-admin` CLI for tenant/budget/RCA operations, admin role with BYPASSRLS |
| Platform | Docker Compose full stack; 215 tests (unit + integration) passing; ruff-clean |

## Quick Start

### Docker Compose

This path is aligned to [docker-compose.yml](docker-compose.yml) and is the fastest way to get a healthy local stack.

```bash
git clone https://github.com/your-handle/gdev-agent.git
cd gdev-agent
cp .env.example .env
docker compose up --build
```

What starts:

| Service | URL / Port | Purpose |
| --- | --- | --- |
| agent | `http://localhost:8000` | FastAPI application |
| postgres | `localhost:5432` | Primary database |
| redis | `localhost:6379` | Rate limit, dedup, approval state |
| n8n | `http://localhost:5678` | Workflow orchestration |
| prometheus | `http://localhost:9090` | Metrics scrape |
| grafana | `http://localhost:3000` | Dashboards |
| tempo | `http://localhost:3200` | Trace backend |
| loki | `http://localhost:3100` | Log backend |

The `migrate` service runs Alembic and seeds the database before the API starts. In the compose stack, `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`, `APPROVE_SECRET`, `WEBHOOK_SECRET_ENCRYPTION_KEY`, `OTLP_ENDPOINT`, and a development `ANTHROPIC_API_KEY` are injected automatically.

Verify the stack:

```bash
curl -i http://localhost:8000/health
```

Expected response:

```http
HTTP/1.1 200 OK
```

```json
{"status":"ok","app":"gdev-agent"}
```

If you want to exercise live LLM behavior instead of the compose default placeholder key, set `ANTHROPIC_API_KEY` in `.env` before startup.

## Environment Variables

Copy [.env.example](.env.example) and adjust only what you need for your environment.

| Variable | Required | Notes |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | Yes for real LLM calls | Required by `get_settings()` at app startup |
| `ANTHROPIC_MODEL` | No | Defaults to `claude-sonnet-4-6` |
| `VOYAGE_API_KEY` | No | Needed for embedding-backed features outside stub mode |
| `EMBEDDING_MODEL` | No | Defaults to `voyage-3-lite` |
| `KB_BASE_URL` | Recommended | FAQ links should also be present in `URL_ALLOWLIST` |
| `REDIS_URL` | Yes | Approval store, rate limiting, dedup, caching |
| `DATABASE_URL` | Yes for Postgres features | Compose provides it automatically |
| `TEST_DATABASE_URL` | No | Test-only override |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | No | Async Postgres pool sizing |
| `WEBHOOK_SECRET` | Optional legacy path | Global webhook secret; per-tenant secret storage is the main design |
| `WEBHOOK_SECRET_ENCRYPTION_KEY` | Recommended | Fernet key for encrypted per-tenant webhook secrets |
| `JWT_SECRET` | Yes outside demo mode | JWT signing secret |
| `JWT_ALGORITHM` | No | Defaults to `HS256` |
| `JWT_TOKEN_EXPIRY_HOURS` | No | Access token lifetime |
| `APPROVE_SECRET` | Recommended | Shared secret for approval callbacks |
| `RATE_LIMIT_RPM` / `RATE_LIMIT_BURST` | No | Request and burst limits |
| `AUTH_RATE_LIMIT_ATTEMPTS` | No | Login throttling |
| `MAX_INPUT_LENGTH` | No | Input guard length cap |
| `AUTO_APPROVE_THRESHOLD` | No | Confidence threshold for auto execution |
| `APPROVAL_CATEGORIES` | No | Comma-separated category list |
| `APPROVAL_TTL_SECONDS` | No | Pending approval expiry |
| `OUTPUT_GUARD_ENABLED` | No | Enables output checks |
| `URL_ALLOWLIST` | No | Comma-separated hostname allowlist |
| `OUTPUT_URL_BEHAVIOR` | No | `strip` or `reject` |
| `RCA_LOOKBACK_HOURS` | No | RCA clustering window |
| `RCA_BUDGET_PER_RUN_USD` | No | Budget cap per RCA run |
| `LINEAR_API_KEY` / `LINEAR_TEAM_ID` | Optional | Ticket creation integration |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_APPROVAL_CHAT_ID` | Optional | Messaging and approval notifications |
| `GOOGLE_SHEETS_CREDENTIALS_JSON` / `GOOGLE_SHEETS_ID` | Optional | Audit export integration |
| `SQLITE_LOG_PATH` | Optional | Enables local SQLite event logging |
| `OTLP_ENDPOINT` / `OTEL_SERVICE_NAME` | Optional | OpenTelemetry export |
| `APP_NAME` / `APP_ENV` / `LOG_LEVEL` | No | App identity and logging controls |
| `ANTHROPIC_INPUT_COST_PER_1K` / `ANTHROPIC_OUTPUT_COST_PER_1K` | No | Cost ledger rates |

## API Overview

### Core workflow

| Endpoint | Purpose |
| --- | --- |
| `POST /webhook` | Main ingestion path for support messages; returns either `executed` or `pending` |
| `POST /approve` | Human decision endpoint for pending actions |
| `GET /health` | Readiness check used by Docker health checks |
| `GET /metrics` | Prometheus scrape endpoint |

### Auth and governance

| Endpoint | Purpose |
| --- | --- |
| `POST /auth/token` | Login and issue JWT |
| `POST /auth/logout` | Blocklist a token |
| `POST /auth/refresh` | Refresh an access token |
| `POST /eval/run` | Start an eval run |
| `GET /eval/runs` | List eval history |

### Tenant read APIs

| Endpoint | Purpose |
| --- | --- |
| `GET /tickets` and `GET /tickets/{ticket_id}` | Ticket history and detail |
| `GET /audit` | Audit log history |
| `GET /metrics/cost` | Cost ledger readout |
| `GET /agents` and `PUT /agents/{agent_id}` | Agent config inspection and versioned updates |
| `GET /clusters` | RCA cluster list |
| `GET /clusters/{cluster_id}` | RCA cluster detail |
| `GET /clusters/{cluster_id}/tickets` | Tickets associated with a cluster |

Most endpoints outside `/health`, `/webhook`, and `/metrics` require JWT auth plus tenant context.

## Request Flow At A Glance

1. A caller sends a support event to `POST /webhook`.
2. Middleware verifies the request signature, applies rate limits, and assigns request correlation.
3. The agent blocks oversized or injection-shaped input before any model call.
4. The LLM classifies the message, extracts entities, and drafts a response.
5. Policy and output-guard checks decide whether the action can auto-execute or must wait for review.
6. The service either executes the tool path immediately or stores a pending approval for `POST /approve`.
7. Audit rows, metrics, and cost tracking capture the outcome.

## Repository Guide

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): system structure, service boundaries, request flow, deployment view.
- [docs/spec.md](docs/spec.md): product scope, API intent, and behavioral contract.
- [docs/N8N.md](docs/N8N.md): n8n integration and approval workflow blueprint.
- [docs/observability.md](docs/observability.md): metrics, tracing, and logging conventions.
- [docs/agent-registry.md](docs/agent-registry.md): agent configuration model and governance.
- [docs/llm-usage.md](docs/llm-usage.md): prompt/versioning and model-usage rules.
- [docs/load-profile.md](docs/load-profile.md): load targets and performance assumptions.
- [docs/data-map.md](docs/data-map.md): schema, Redis keys, and tenant-boundary rules.
- [n8n/README.md](n8n/README.md): workflow assets committed in this repository.

## Current State

The platform is feature-complete for a pilot deployment. It includes the multi-tenant storage foundation, JWT/RBAC boundary, approval hardening, eval APIs with budget enforcement, auth service flows, embedding persistence, RCA clustering with persisted cluster membership, full service-layer separation (no FastAPI imports in business logic), Dockerized observability, admin CLI, and the n8n workflow artifacts needed for demo or pilot-style setups.

**215 tests pass** (unit + integration, including RLS isolation, migration up/down, cross-tenant rejection, and cluster membership persistence). All P0 and P1 findings from 13 review cycles have been resolved.

The main value is the governed request pipeline: webhook in → guardrails → LLM-assisted triage → human approval where needed → auditable execution throughout, with tenant isolation enforced at the database layer and observable at every step.
