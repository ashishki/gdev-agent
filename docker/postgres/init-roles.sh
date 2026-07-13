#!/usr/bin/env bash
set -Eeuo pipefail

: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${GDEV_APP_PASSWORD:?GDEV_APP_PASSWORD is required}"

# The official Postgres image creates POSTGRES_USER as a cluster superuser. Keep
# that bootstrap identity separate from the request-serving role and provision
# the latter without embedding its password in migration history.
psql \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=ON_ERROR_STOP=1 \
  --set=app_password="$GDEV_APP_PASSWORD" <<'SQL'
SELECT format(
    'CREATE ROLE gdev_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L',
    :'app_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gdev_app')
\gexec

ALTER ROLE gdev_app
    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;

SELECT format('ALTER ROLE gdev_app PASSWORD %L', :'app_password')
\gexec
SQL
