#!/usr/bin/env bash
set -Eeuo pipefail

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "ERROR: docker compose is required" >&2
  exit 2
fi

mapfile -t POSTGRES_CONTAINERS < <("${COMPOSE[@]}" ps -q postgres)
if [[ "${#POSTGRES_CONTAINERS[@]}" -ne 1 || -z "${POSTGRES_CONTAINERS[0]}" ]]; then
  echo "ERROR: expected exactly one running Compose postgres container" >&2
  exit 2
fi
POSTGRES_CONTAINER="${POSTGRES_CONTAINERS[0]}"

owner_psql() {
  docker exec -i "$POSTGRES_CONTAINER" sh -ec \
    'exec psql -X -qAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
}

app_psql() {
  docker exec -i "$POSTGRES_CONTAINER" sh -ec \
    'PGPASSWORD="$GDEV_APP_PASSWORD" exec psql -X -qAt -v ON_ERROR_STOP=1 -h localhost -U gdev_app -d "$POSTGRES_DB"'
}

role_flags="$(owner_psql <<'SQL'
SELECT rolsuper, rolbypassrls
FROM pg_roles
WHERE rolname = 'gdev_app';
SQL
)"
if [[ "$role_flags" != "f|f" ]]; then
  echo "ERROR: gdev_app must be NOSUPERUSER NOBYPASSRLS; observed ${role_flags:-missing}" >&2
  exit 1
fi
echo "PASS role_flags gdev_app rolsuper=f rolbypassrls=f"

table_topology="$(owner_psql <<'SQL'
WITH expected(table_name) AS (
  VALUES
    ('tenant_users'),
    ('api_keys'),
    ('webhook_secrets'),
    ('tickets'),
    ('ticket_classifications'),
    ('ticket_extracted_fields'),
    ('proposed_actions'),
    ('pending_decisions'),
    ('approval_events'),
    ('audit_log'),
    ('ticket_embeddings'),
    ('cluster_summaries'),
    ('rca_cluster_members'),
    ('agent_configs'),
    ('cost_ledger'),
    ('eval_runs')
), topology AS (
  SELECT e.table_name,
         pg_get_userbyid(c.relowner) AS owner_name,
         c.relrowsecurity,
         c.relforcerowsecurity
  FROM expected e
  LEFT JOIN pg_class c
    ON c.relname = e.table_name
   AND c.relnamespace = 'public'::regnamespace
)
SELECT count(*),
       count(*) FILTER (
         WHERE owner_name IS DISTINCT FROM 'gdev_owner'
            OR relrowsecurity IS DISTINCT FROM TRUE
            OR relforcerowsecurity IS DISTINCT FROM TRUE
       )
FROM topology;
SQL
)"
if [[ "$table_topology" != "16|0" ]]; then
  echo "ERROR: tenant table topology expected 16|0, observed ${table_topology:-missing}" >&2
  exit 1
fi
echo "PASS table_topology expected=16 owner=gdev_owner rls=enabled force_rls=true"

tenant_a_scope="$(app_psql <<'SQL' | tail -n 1
SELECT set_config(
  'app.current_tenant_id',
  'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
  FALSE
);
SELECT count(*), count(DISTINCT tenant_id), min(tenant_id::text)
FROM tenant_users;
SQL
)"
if [[ "$tenant_a_scope" != "1|1|aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa" ]]; then
  echo "ERROR: tenant-A isolation expected 1|1|tenant-A, observed ${tenant_a_scope:-missing}" >&2
  exit 1
fi
echo "PASS tenant_a_isolation rows=1 tenant_ids=1 tenant=aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

probe_message="rls-cross-tenant-proof"
if cross_insert_error="$(app_psql 2>&1 <<SQL
BEGIN;
SELECT set_config(
  'app.current_tenant_id',
  'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
  TRUE
);
INSERT INTO tickets (tenant_id, message_id, user_id_hash, raw_text)
VALUES (
  'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
  '${probe_message}',
  'sanitized-proof-user',
  'sanitized RLS rejection probe'
);
ROLLBACK;
SQL
)"
then
  echo "ERROR: cross-tenant INSERT unexpectedly succeeded" >&2
  exit 1
fi
if [[ "$cross_insert_error" != *"row-level security policy"* ]]; then
  echo "ERROR: cross-tenant INSERT failed for a reason other than RLS" >&2
  exit 1
fi

persisted_probe="$(owner_psql <<SQL
SELECT count(*) FROM tickets WHERE message_id = '${probe_message}';
SQL
)"
if [[ "$persisted_probe" != "0" ]]; then
  echo "ERROR: rejected probe left ${persisted_probe} persisted row(s)" >&2
  exit 1
fi
echo "PASS cross_tenant_insert rejected=true persisted_rows=0"
