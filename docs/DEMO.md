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

## Default Demo Values

These defaults match the seeded local Compose stack in [`docker/seed.sql`](/home/gdev/gdev-agent/docker/seed.sql) and [`docker-compose.yml`](/home/gdev/gdev-agent/docker-compose.yml):

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

## Run

Use the project environment that already has `httpx` installed:

```bash
python scripts/demo.py
```

Override the API URL if needed:

```bash
python scripts/demo.py --url http://localhost:8001
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
[2026-03-20 15:00:00 UTC] [STEP] Health check
[2026-03-20 15:00:00 UTC] [DONE] Health check (0.02s)
[2026-03-20 15:00:00 UTC] [STEP] Auth token
[2026-03-20 15:00:00 UTC] [DONE] Auth token (0.08s)
[2026-03-20 15:00:00 UTC] [STEP] Send webhook
[2026-03-20 15:00:01 UTC] [DONE] Send webhook (0.41s)
[2026-03-20 15:00:01 UTC] [STEP] Wait for pending audit row
[2026-03-20 15:00:01 UTC] [DONE] Wait for pending audit row (0.05s)
[2026-03-20 15:00:01 UTC] [STEP] Approve pending action
[2026-03-20 15:00:01 UTC] [DONE] Approve pending action (0.06s)
[2026-03-20 15:00:01 UTC] [OK] Demo completed for pending_id=... in 0.62s
```

On failure the script exits non-zero and prints the failing step or HTTP error to `stderr`.
