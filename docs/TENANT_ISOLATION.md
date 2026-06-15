# Tenant Isolation Boundary Proof

This is the canonical tenant isolation and security boundary proof for the
local reliability track. It is scoped to repository code, migrations, and local
tests. It does not claim external production readiness, managed cloud network
isolation, tenant-facing admin consoles, or live customer traffic.
The protected boundaries below cover RLS, tenant-scoped JWT, webhook signature,
approval boundaries, tenant secret isolation, and cost ledger separation. The
Not Protected section states what this local proof does not protect.

## Reviewer Entry Point

Run the current tenant-boundary proof with:

```bash
.venv/bin/python -m pytest tests/test_isolation.py tests/test_rbac.py tests/test_auth_service.py tests/test_secrets_store.py tests/test_cost_ledger.py tests/test_approval_flow.py tests/test_middleware.py tests/test_webhook_service.py tests/test_endpoints.py tests/test_redis_approval_store.py -q
```

Some RLS and cost-ledger tests require Docker or `TEST_DATABASE_URL`. If no
Postgres test database is available, pytest marks those integration checks as
explicit skips instead of treating infrastructure as silently present.

## Protected Boundaries

| Boundary | What is protected | Enforcement | Proof |
|----------|-------------------|-------------|-------|
| Postgres RLS | Tenant-scoped durable tables only expose rows matching the transaction tenant context. Cross-tenant reads return no rows. | `alembic/versions/0001_initial_schema.py` enables RLS and creates `tenant_isolation` policies for tenant-scoped tables; `alembic/versions/0005_cluster_membership.py` adds the cluster membership policy. | `tests/test_isolation.py::test_db_rls_read_isolation_for_gdev_app` |
| RLS writes | The application DB role cannot write rows for a different tenant context. | `gdev_app` receives table grants without `BYPASSRLS`; tenant context is set before scoped queries. | `tests/test_isolation.py::test_db_rls_write_isolation_for_gdev_app` |
| Transaction tenant context | Tenant context is transaction-local, not connection-global, so pooled or reused sessions do not retain another tenant's context. | `app/db.py::_set_tenant_ctx` executes `SELECT set_config('app.current_tenant_id', :tenant_id, true)` inside `session.begin()`, equivalent to `SET LOCAL`. | `tests/test_isolation.py::test_db_rls_read_isolation_for_gdev_app`, `tests/test_secrets_store.py::test_get_secret_decrypts_ciphertext` |
| Pipeline persistence | Ticket, classification, extraction, proposed action, and audit rows are bound to the payload tenant. | `app/store.py::EventStore.persist_pipeline_run` rejects tenant mismatch and writes all rows under one tenant context. | `tests/test_isolation.py::test_event_store_binds_all_rows_to_payload_tenant` |
| tenant-scoped JWT | Protected read/admin endpoints receive tenant, user, role, and JTI from a signed JWT; route dependencies enforce allowed roles, and read APIs reject tokens missing a tenant claim. | `app/services/auth_service.py` issues `tenant_id` claims after tenant-slug scoping; `app/middleware/auth.py` decodes the token, checks the blocklist, and stores tenant/user/role on `request.state`; `app/dependencies.py::require_role` gates routes. | `tests/test_auth_service.py::test_login_returns_token_and_records_observability`, `tests/test_auth_service.py::test_login_rejects_user_when_tenant_slug_does_not_match`, `tests/test_rbac.py::test_tenant_read_routes_require_jwt_reader_roles`, `tests/test_rbac.py::test_tenant_read_api_rejects_jwt_without_tenant_claim`, `tests/test_endpoints.py::test_auth_logout_revokes_token_for_next_request` |
| Tenant read APIs | Tenant-scoped read endpoints assemble queries from the JWT tenant context, not caller-supplied tenant identifiers. | `app/routers/analytics.py::list_audit` and peer read APIs take `request.state.tenant_id` from JWT middleware and query with named tenant parameters. | `tests/test_endpoints.py::test_tenant_a_cannot_read_tenant_b_audit_logs` |
| webhook signature | Webhook callers must present `X-Tenant-Slug` and an HMAC-SHA256 signature over the raw body using that tenant's active secret. A secret from another tenant, an invalid slug, or an invalid HMAC does not reach downstream webhook handling. | `app/middleware/signature.py` resolves the tenant slug, retrieves the tenant's encrypted secret via `WebhookSecretStore`, verifies with `hmac.compare_digest`, and injects tenant context into ASGI state. | `tests/test_middleware.py::test_correct_signature_passes`, `tests/test_middleware.py::test_tampered_body_with_old_signature_rejected`, `tests/test_middleware.py::test_unknown_tenant_slug_rejected`, `tests/test_middleware.py::test_invalid_tenant_slug_rejected_predictably`, `tests/test_middleware.py::test_cross_tenant_secret_rejected`, `tests/test_middleware.py::test_invalid_hmac_rejected_before_downstream_side_effects` |
| Tenant secret isolation | Webhook secrets are stored per tenant, encrypted at rest, and are not copied into Redis. Secret lookups set tenant context before reading `webhook_secrets`. | `app/secrets_store.py::WebhookSecretStore` decrypts Fernet ciphertext from Postgres after `_set_tenant_ctx`; Redis stores no decrypted tenant webhook secrets. | `tests/test_secrets_store.py::test_get_secret_decrypts_ciphertext`, `tests/test_secrets_store.py::test_get_secret_by_slug_reads_tenant_then_secret`, `tests/test_secrets_store.py::test_get_secret_by_slug_returns_slug_specific_secret` |
| Approval boundary | A JWT tenant can only read/pop pending decisions under the same tenant namespace; wrong-tenant approval attempts do not execute actions and leave the original pending item intact. | `app/main.py::approve` requires `support_agent` or `tenant_admin`; `app/services/approval_service.py` verifies the approval secret when configured; `app/agent.py::approve` uses the JWT tenant for pending lookup; `app/approval_store.py` keys pending items as `{tenant_id}:pending:{pending_id}`. | `tests/test_rbac.py::test_viewer_role_cannot_call_approve`, `tests/test_approval_flow.py::test_approve_forbidden_on_cross_tenant_pending`, `tests/test_approval_flow.py::test_cross_tenant_approval_does_not_execute_action`, `tests/test_approval_flow.py::test_tenant_a_cannot_approve_tenant_b_pending_action`, `tests/test_isolation.py::test_approve_cross_tenant_is_forbidden_and_pending_remains`, `tests/test_redis_approval_store.py::test_pending_is_isolated_by_tenant` |
| Cost ledger separation | Daily budget checks and usage writes are tenant-scoped. One tenant exhausting budget does not block another tenant, and RLS rejects cross-tenant usage writes. | `alembic/versions/0001_initial_schema.py` places `cost_ledger` under RLS and adds `UNIQUE(tenant_id, date)`; `app/cost_ledger.py` checks and records by tenant. | `tests/test_cost_ledger.py::test_budget_exhausted_returns_429_before_llm_call`, `tests/test_cost_ledger.py::test_record_uses_upsert_and_accumulates_daily_usage`, `tests/test_cost_ledger.py::test_record_rejects_cross_tenant_usage_under_rls`, `tests/test_cost_ledger.py::test_check_budget_isolated_per_tenant` |
| Rate and replay namespaces | Webhook rate limits and deduplication keys are tenant-prefixed so tenant traffic does not collide. | `app/middleware/rate_limit.py` keys counters by tenant and user; `app/dedup.py` keys cached webhook responses by tenant and message. | `tests/test_middleware.py::test_rate_limits_are_independent_per_user`, `tests/test_middleware.py::test_webhook_key_uses_tenant_first_order`, `tests/test_webhook_service.py::test_duplicate_webhook_replay_is_idempotent_for_side_effects` |

## Not Protected

These are explicit limits of the current local proof:

- The local proof does not verify cloud VPC rules, managed Redis ACLs,
  database network firewalls, TLS termination, WAF rules, or a deployed
  production ingress path.
- `/metrics` is intentionally JWT-exempt for Prometheus scraping; access is
  expected to be restricted by network placement, not by application JWT auth.
- `gdev_admin` is intentionally privileged for migrations and maintenance and
  can bypass RLS. It is not an application request role.
- The Anthropic API key is shared at provider level. Per-tenant spend is guarded
  by the local `cost_ledger`, not by provider-side tenant credentials.
- Redis tenant isolation is application namespace isolation in the local stack.
  Per-tenant Redis ACLs are a production hardening item, not part of this proof.
- Demo, eval, and load fixtures are synthetic. This document does not prove
  behavior under live customer data or real tenant operations.

## Exact Migration Proof

| Migration | Isolation work |
|-----------|----------------|
| `alembic/versions/0001_initial_schema.py` | Defines tenant-scoped tables including `tenant_users`, `api_keys`, `webhook_secrets`, `tickets`, `pending_decisions`, `approval_events`, `audit_log`, `agent_configs`, `cost_ledger`, and `eval_runs`; enables RLS for each table; creates `tenant_isolation` policies using `current_setting('app.current_tenant_id', TRUE)::UUID`; creates `gdev_app` and `gdev_admin` roles. |
| `alembic/versions/0002_grant_admin_bypassrls.py` | Grants `BYPASSRLS` only to `gdev_admin`, keeping the application role separate from migration/admin maintenance privileges. |
| `alembic/versions/0005_cluster_membership.py` | Adds RLS for `rca_cluster_members` through the owning `cluster_summaries.tenant_id`, so cluster membership reads follow the tenant context. |

## Exact Test Proof

| Claim | Tests |
|-------|-------|
| RLS read/write isolation | `tests/test_isolation.py::test_db_rls_read_isolation_for_gdev_app`, `tests/test_isolation.py::test_db_rls_write_isolation_for_gdev_app` |
| Admin bypass is deliberate and separate from app role | `tests/test_isolation.py::test_gdev_admin_has_bypassrls_and_sees_both_tenants` |
| Pipeline rows are tenant-bound | `tests/test_isolation.py::test_event_store_binds_all_rows_to_payload_tenant` |
| JWT tenant and route role boundaries | `tests/test_auth_service.py::test_login_returns_token_and_records_observability`, `tests/test_auth_service.py::test_login_rejects_user_when_tenant_slug_does_not_match`, `tests/test_rbac.py::test_tenant_read_routes_require_jwt_reader_roles`, `tests/test_rbac.py::test_tenant_read_api_rejects_jwt_without_tenant_claim`, `tests/test_endpoints.py::test_auth_logout_revokes_token_for_next_request`, `tests/test_endpoints.py::test_reader_roles_allowed_for_jwt_read_endpoints`, `tests/test_rbac.py::test_viewer_role_cannot_call_approve` |
| Tenant read API adversarial boundary | `tests/test_endpoints.py::test_tenant_a_cannot_read_tenant_b_audit_logs` |
| Webhook HMAC and per-tenant secret rejection | `tests/test_middleware.py::test_correct_signature_passes`, `tests/test_middleware.py::test_tampered_body_with_old_signature_rejected`, `tests/test_middleware.py::test_unknown_tenant_slug_rejected`, `tests/test_middleware.py::test_invalid_tenant_slug_rejected_predictably`, `tests/test_middleware.py::test_cross_tenant_secret_rejected`, `tests/test_middleware.py::test_invalid_hmac_rejected_before_downstream_side_effects`, `tests/test_secrets_store.py::test_get_secret_decrypts_ciphertext`, `tests/test_secrets_store.py::test_get_secret_by_slug_reads_tenant_then_secret`, `tests/test_secrets_store.py::test_get_secret_by_slug_returns_slug_specific_secret` |
| Approval cross-tenant rejection | `tests/test_approval_flow.py::test_approve_forbidden_on_cross_tenant_pending`, `tests/test_approval_flow.py::test_cross_tenant_approval_does_not_execute_action`, `tests/test_approval_flow.py::test_tenant_a_cannot_approve_tenant_b_pending_action`, `tests/test_isolation.py::test_approve_cross_tenant_is_forbidden_and_pending_remains`, `tests/test_redis_approval_store.py::test_pending_is_isolated_by_tenant` |
| Cost ledger separation | `tests/test_cost_ledger.py::test_budget_exhausted_returns_429_before_llm_call`, `tests/test_cost_ledger.py::test_record_uses_upsert_and_accumulates_daily_usage`, `tests/test_cost_ledger.py::test_record_rejects_cross_tenant_usage_under_rls`, `tests/test_cost_ledger.py::test_check_budget_isolated_per_tenant` |
| Rate limit and replay namespaces | `tests/test_middleware.py::test_rate_limits_are_independent_per_user`, `tests/test_middleware.py::test_webhook_key_uses_tenant_first_order`, `tests/test_webhook_service.py::test_duplicate_webhook_replay_is_idempotent_for_side_effects` |

## Failure Taxonomy Links

- `FM_CROSS_TENANT_APPROVAL` covers approval attempts using a tenant context
  that does not own the pending decision.
- `FM_APPROVAL_TTL_EXPIRED` covers stale approval tokens.
- `FM_RATE_LIMIT_EXCEEDED` covers bounded 429 behavior before downstream model
  or action work.
- `FM_BUDGET_EXCEEDED` covers budget blocks before LLM spend.
- `FM_DUPLICATE_WEBHOOK_REPLAY` covers tenant-scoped idempotency for repeated
  webhook deliveries.

See [FAILURE_MODES.md](FAILURE_MODES.md) for the runbook taxonomy,
[SLO_RUNBOOK.md](SLO_RUNBOOK.md) for local operational targets, and
[data-map.md#6-tenant-isolation-model](data-map.md#6-tenant-isolation-model)
for the lower-level storage and Redis namespace model.
