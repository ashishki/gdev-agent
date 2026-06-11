# Demo Script

`scripts/demo.py` runs the happy-path approval flow against a local `gdev-agent` stack: login, signed webhook, wait for the pending audit row, approve, and exit `0` on success.

## Prerequisites

- Docker and Docker Compose are installed.
- The local stack is running from the repo root:

```bash
docker compose up --build -d
```

- The API is reachable at `http://localhost:8000` unless you override it with `--url`.
- If your local app is not using the seeded demo tenant values, set the environment overrides below before running the script.
- For the free deterministic path, run the API with `LLM_MODE=demo`. Live mode
  is optional and requires `LLM_MODE=live`, a real `ANTHROPIC_API_KEY`, and a
  tenant budget cap.

## Default Demo Values

These defaults match the seeded local Compose stack in
[`docker/seed.sql`](../docker/seed.sql), [`scripts/seed_db.py`](../scripts/seed_db.py),
and [`docker-compose.yml`](../docker-compose.yml). They are synthetic local
demo values only.

| Tenant | Tenant ID | Webhook secret | Admin user | Admin password | Approval secret | Reviewer |
| --- | --- | --- | --- | --- | --- | --- |
| `test-tenant-a` | `aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa` | `test-webhook-secret-a` | `admin-a@example.com` | `password123` | `approve-secret` | `demo-runner` |
| `test-tenant-b` | `bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb` | `test-webhook-secret-b` | `admin-b@example.com` | `password123` | `approve-secret` | `demo-runner` |

The default `scripts/demo.py` run uses tenant A:

- `DEMO_TENANT_SLUG=test-tenant-a`
- `DEMO_TENANT_ID=aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa`
- `DEMO_WEBHOOK_SECRET=test-webhook-secret-a`
- `DEMO_ADMIN_EMAIL=admin-a@example.com`
- `DEMO_ADMIN_PASSWORD=password123`
- `DEMO_APPROVE_SECRET=approve-secret`
- `DEMO_REVIEWER=demo-runner`

Optional timing controls:

- `DEMO_POLL_INTERVAL=1.0`
- `DEMO_TIMEOUT_SECONDS=30.0`
- `DEMO_LLM_MODE=demo`

## LLM Mode

The local review path should use deterministic demo mode:

```bash
printf "\nLLM_MODE=demo\n" >> .env
docker compose up --build -d
python scripts/demo.py --llm-mode demo
```

Demo mode routes model calls through committed fixture logic inside
`app/llm_client.py`; it still uses the same input guard, policy, output guard,
approval, audit, cost, and webhook service boundaries as live mode.

Live LLM mode remains available for manual experiments:

```bash
printf "\nLLM_MODE=live\nANTHROPIC_API_KEY=sk-...\n" >> .env
docker compose up --build -d
python scripts/demo.py --llm-mode live
```

Use live mode only with an explicit API key, a small tenant `daily_budget_usd`,
and awareness that paid provider calls may occur.

## Support Case Fixtures

The demo fixture contract includes representative webhook payloads in
[`load_tests/fixtures/sample_messages.jsonl`](../load_tests/fixtures/sample_messages.jsonl).
`scripts/seed_db.py` records the same message IDs in `DEMO_SUPPORT_CASES` so
tests fail if docs, fixtures, or seed assumptions drift.

| Case type | Message ID | Tenant | Purpose |
| --- | --- | --- | --- |
| normal | `sample-normal-01` | `test-tenant-a` | Low-risk gameplay/settings request |
| risky | `sample-risky-01` | `test-tenant-a` | Billing refund case that should require approval |
| adversarial | `sample-adversarial-01` | `test-tenant-b` | Prompt-injection shaped support text |
| low_confidence | `sample-low-confidence-01` | `test-tenant-a` | Ambiguous issue report for escalation behavior |
| duplicate | `sample-duplicate-01` | `test-tenant-a` | Two committed rows with the same `message_id` for replay/idempotency checks |

## Run

Use the single-command wrapper for the deterministic local path:

```bash
make demo
```

Equivalent direct wrapper:

```bash
bash scripts/demo.sh
```

Use the project environment that already has `httpx` installed if calling the
Python runner directly:

```bash
python scripts/demo.py --llm-mode demo
```

Override the API URL if needed:

```bash
python scripts/demo.py --url http://localhost:8001 --llm-mode demo
```

Example with explicit env overrides:

```bash
DEMO_TENANT_SLUG=test-tenant-a \
DEMO_WEBHOOK_SECRET=test-webhook-secret-a \
DEMO_ADMIN_EMAIL=admin-a@example.com \
DEMO_ADMIN_PASSWORD=password123 \
python scripts/demo.py --url http://localhost:8000
```

## Expected Output

Each step prints a UTC timestamp plus per-step timing. A successful run looks like:

```text
[2026-03-20 15:00:00 UTC] [START] Base URL http://localhost:8000
[2026-03-20 15:00:00 UTC] [MODE] Expected server LLM mode: demo
[2026-03-20 15:00:00 UTC] [STEP] Health check
[2026-03-20 15:00:00 UTC] [DONE] Health check (0.02s)
[2026-03-20 15:00:00 UTC] [STEP] Auth token
[2026-03-20 15:00:00 UTC] [DONE] Auth token (0.08s)
[2026-03-20 15:00:00 UTC] [STEP] Send signed webhook
[2026-03-20 15:00:01 UTC] [DONE] Send signed webhook (0.41s)
[2026-03-20 15:00:01 UTC] [PENDING] Pending approval created: ...
[2026-03-20 15:00:01 UTC] [STEP] Audit lookup for pending row
[2026-03-20 15:00:01 UTC] [DONE] Audit lookup for pending row (0.05s)
[2026-03-20 15:00:01 UTC] [STEP] Approve pending action
[2026-03-20 15:00:01 UTC] [DONE] Approve pending action (0.06s)
[2026-03-20 15:00:01 UTC] [APPROVED] Approval decision status=approved
[2026-03-20 15:00:01 UTC] [STEP] Metrics check
[2026-03-20 15:00:01 UTC] [DONE] Metrics check (0.03s)
[2026-03-20 15:00:01 UTC] [OK] Demo completed for pending_id=... in 0.62s
```

On failure the script exits non-zero and prints the failing step or HTTP error to `stderr`.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `stack unavailable` | API container is not running or URL is wrong | Run `docker compose up --build -d` and check `BASE_URL` |
| `auth failed; verify docker/seed.sql was applied` | Seed data is missing or demo credentials drifted | Re-run the `migrate` service or restart Compose after checking `docker/seed.sql` |
| `signed webhook failed` | Tenant slug or webhook secret mismatch | Use the defaults table above or update `DEMO_TENANT_SLUG` and `DEMO_WEBHOOK_SECRET` together |
| `webhook did not produce pending state` | Server is not in deterministic mode or billing policy changed | Set `LLM_MODE=demo` in `.env` and keep `approval_categories` including `billing` |
| `metrics endpoint did not include gdev workflow metrics` | Metrics route unavailable or app did not initialize metrics | Check `GET /metrics` and container logs |
