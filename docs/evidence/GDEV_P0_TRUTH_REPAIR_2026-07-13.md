# gdev-agent P0 Truth Repair Evidence

Date: 2026-07-13

Scope: local P0 security, CI, eval-contract, and evidence repair

Verification branch: `agent/gdev-p0-truth-repair`

Starting revision: `d33d842f05edafa225ecd7144d51614837ff6d6f`

This is bounded local evidence. It does not claim a hosted deployment, real
users, production traffic, production SLOs, or model quality on customer data.
The isolated worktree was committed only after the checks below; remote GitHub
Actions is a separate merge gate and is not inferred from these local results.
Commands below abbreviate the already-installed shared project environment as
`.venv/bin`; the interpreter actually lived in the untouched primary checkout,
while every command's working directory and imported source were this isolated
verification worktree.
The two pre-existing dirty paths in the primary checkout were neither modified
nor staged by this work.

## Implemented Repair

- Default Compose now bootstraps/migrates with `gdev_owner` and serves requests
  with the distinct `gdev_app` login. Both passwords are required environment
  variables; the request role is normalized to `NOSUPERUSER NOBYPASSRLS`.
- Migration `0007_enforce_compose_rls_topology.py` grants schema/table/sequence
  access to `gdev_app` without ownership and applies `ENABLE` plus `FORCE ROW
  LEVEL SECURITY` to all 16 tenant-scoped tables, including
  `rca_cluster_members`.
- `scripts/verify_compose_rls.sh` provides a sanitized executable proof of role
  flags, table ownership/FORCE RLS, tenant-A read isolation, and cross-tenant
  write rejection. CI runs the same proof against the default Compose topology,
  followed by the normal auth/approval demo.
- The unused Grafana PostgreSQL datasource was removed. The committed dashboard
  uses Prometheus panels; repository observability tests already assert that no
  panel selects the PostgreSQL datasource.
- The internal eval runner derives classification categories from
  `app.schemas.Category` and accepts `blocked`/`guard_blocked` as a valid safety
  result in direct and persisted-job paths.
- The tracked Python bytecode artifacts were removed. Ruff was pinned to the
  version used to produce the formatting baseline, and the five pre-existing
  source/test formatting failures were normalized.

## Final Verification Results

### Source gates

```bash
.venv/bin/ruff format --check app/ tests/ scripts/ eval/ \
  alembic/versions/0007_enforce_compose_rls_topology.py
.venv/bin/ruff check app/ tests/ scripts/ eval/ \
  alembic/versions/0007_enforce_compose_rls_topology.py
GDEV_OWNER_PASSWORD='<redacted>' GDEV_APP_PASSWORD='<redacted>' \
  docker-compose config --quiet
```

Result:

```text
97 files already formatted
All checks passed!
compose config: exit 0
```

### Full test suite

```bash
PYTHONDWRITEBYTECODE=1 LLM_MODE=demo \
  .venv/bin/python -m pytest tests/ -q --tb=short
```

Result:

```text
310 passed, 45 warnings in 106.16s
```

All 45 warnings are the existing Alembic `path_separator` deprecation warning
emitted by container-backed migration fixtures. No test was skipped in the
final run. The full-suite run initially exposed a teardown case where a test
intentionally removes `audit_log`; the new downgrade was made idempotent with
`ALTER TABLE IF EXISTS`, and both the targeted regression and final full suite
then passed.

### Internal 180-case eval

```bash
PYTHONDONTWRITEBYTECODE=1 LLM_MODE=demo \
  .venv/bin/python -m eval.runner --gate
```

Result from `eval/results/last_run.json`:

Dataset SHA-256:
`8db471b52ea78f6bf9daa3993630f57083277660f31ced8e85790860e0b98400`.

| Metric | Value |
| --- | ---: |
| total cases | 180 |
| scored cases | 159 |
| correct classifications | 27 |
| classification accuracy | 0.1698 |
| guard blocks / expected guard blocks | 21 / 18 |
| guard block rate | 1.0000 |
| risk routing recall | 0.5370 |
| unsafe auto approvals / expected safety routes | 75 / 162 |
| unsafe auto-approval rate | 0.4630 |
| invalid structured outputs | 0 |
| human escalations | 69 |
| human escalation rate | 0.3833 |
| cost per case | 0.0000 USD |
| local latency per case | 10.060 ms |
| threshold gate | passed |

No dataset labels or gate thresholds changed. The weak classification score is
kept visible. This is synthetic deterministic smoke/gap-discovery evidence, not
a production model-quality result. The existing seeded-failure CLI regression
also verifies that a threshold failure exits non-zero.

Eval scopes are deliberately separate:

- internal gdev-agent smoke: 180 cases, executed above;
- Eval Lab conformance baseline: 55 cases, separately committed as 55/55;
- Eval Lab challenge diagnostic: an executable 100-case gate with 90 external
  candidate calls and 10 labeled deterministic fault injections, but no
  canonical external-system run for this fixed gdev revision yet.

### Clean default-Compose isolation proof

The stack was created under an isolated Compose project with passwords supplied
only through environment variables. The proof output was:

```text
PASS role_flags gdev_app rolsuper=f rolbypassrls=f
PASS table_topology expected=16 owner=gdev_owner rls=enabled force_rls=true
PASS tenant_a_isolation rows=1 tenant_ids=1 tenant=aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa
PASS cross_tenant_insert rejected=true persisted_rows=0
```

The normal deterministic demo then completed this sequence against the same
stack:

```text
health -> auth token -> signed webhook -> pending approval -> audit lookup
       -> approve -> metrics
result: OK (2.49s local wall time)
```

No database password was printed or stored in this artifact. After the proof,
all temporary project containers and its network were removed with Compose
`down --volumes --remove-orphans`.

## Evidence Boundary

- The Compose proof covers the repository's default local topology, not a
  managed/cloud database or network boundary.
- The demo tenants, messages, and credentials are synthetic fixtures.
- The test and latency numbers are a dated local run, not performance or
  reliability claims for external traffic.
- The Eval Lab 100-case challenge remains without a canonical external-system
  result until its executable gate records this fixed gdev revision; unit-test
  fixtures are not promoted as evidence of the service.
