# gdev-agent Maintainer and Evidence Surface Verification

Date: 2026-07-13

Scope: security/defect intake, human-approval diagram, and canonical Eval Lab
failure preview

Starting revision: `64b9cec85d990d63ddf17e1ccf26ad5b73114185`

Verification branch: `agent/maintainer-evidence-surface`

This is local verification for documentation, a deterministic renderer, issue
configuration, and their contract tests. It does not claim a new gdev-agent
quality result, production readiness, external use, or a security audit. The
canonical challenge preview remains historical evidence for exact candidate
`0e4c5f0fd50382bbf12ffd35cfca4632384fb0cc`.

## Source and Contract Gates

Commands used the existing project virtual environment while the working
directory and imported repository source were the isolated clean clone.

```bash
ruff check app/ tests/ scripts/ eval/ \
  alembic/versions/0007_enforce_compose_rls_topology.py
ruff format --check app/ tests/ scripts/ eval/ \
  alembic/versions/0007_enforce_compose_rls_topology.py
PYTHONDONTWRITEBYTECODE=1 LLM_MODE=demo \
  python -m pytest tests/ -q --tb=short
PYTHONDONTWRITEBYTECODE=1 LLM_MODE=demo \
  python -m eval.runner --gate --no-write
```

Observed results:

```text
ruff check: All checks passed!
ruff format: 98 files already formatted
pytest: 312 passed, 45 warnings in 109.15s
eval: threshold_result.passed=true; dataset SHA-256
      8db471b52ea78f6bf9daa3993630f57083277660f31ced8e85790860e0b98400
```

The 45 warnings are the existing Alembic `path_separator` deprecation warning
from container-backed fixtures. The eval command used `--no-write`, so its
machine-local timing did not replace the committed dated baseline.

## Content-Addressed Preview Check

Eval Lab annotated tag `v0.2.0` peeled to
`64e6ab384883604e210ba7420529aaecf37f30ed`. The renderer read the tagged
`challenge-run.json` and manifest from an adjacent checkout, verified raw
summary SHA-256
`d4bb0dec70d75de8d33d16f583a01ecbc17bf202ae04509d3dec63087a7b3a3b`,
and accepted manifest content address
`sha256:656face21f27b496d4d3e8bb0b588824f5737d122c1275c710f3e5b15ff94b4b`.

```bash
python scripts/render_eval_failure_preview.py \
  --summary ../Eval-Ground-Truth-Lab/docs/evidence/releases/v0.2.0/gdev-agent-challenge/challenge-run.json \
  --manifest ../Eval-Ground-Truth-Lab/docs/evidence/releases/v0.2.0/gdev-agent-challenge/sha256-656face21f27b496d4d3e8bb0b588824f5737d122c1275c710f3e5b15ff94b4b.manifest.json \
  --output docs/assets/gdev-eval-lab-challenge-fail.svg \
  --check
```

Result: exit `0`. Generated SVG SHA-256:
`091ad0ad87bab99b8216603f57ef79266ce6f9950ed33a77a4167f04a58ec770`.
An intentionally modified temporary copy of `challenge-run.json` was rejected
with `challenge-run.json does not match its manifest digest`; no preview was
accepted from the tampered input.
The SVG was also parsed as XML and rendered locally to a temporary PNG for
visual inspection; the PNG was not committed.

## Default Compose Proof

An isolated Compose project named `gdev_maintainer_surface` built and started
`postgres`, `redis`, `migrate`, and `agent`. The repository proof returned:

```text
PASS role_flags gdev_app rolsuper=f rolbypassrls=f
PASS table_topology expected=16 owner=gdev_owner rls=enabled force_rls=true
PASS tenant_a_isolation rows=1 tenant_ids=1 tenant=aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa
PASS cross_tenant_insert rejected=true persisted_rows=0
```

The deterministic demo then completed health, auth, signed webhook, pending
audit lookup, one-time approval, and metrics checks. All project containers,
volumes, and its network were removed after verification.

Local verification used the available `docker-compose` 1.29.2 fallback. GitHub
Actions remains the separate exact-head gate for the workflow's `docker compose`
execution.

## Workspace Boundary

All changes and checks ran in
`.portfolio-audit-worktrees/gdev-maintainer-surface`. The primary checkout's
pre-existing dirty `app/jobs/rca_clusterer.py` and
`eval/__pycache__/runner.cpython-312.pyc` were not edited, staged, or reset.
