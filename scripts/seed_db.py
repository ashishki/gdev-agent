"""Apply docker seed SQL against configured Postgres."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import asyncpg

DEMO_APPROVE_SECRET = "approve-secret"
DEMO_REVIEWER = "demo-runner"

DEMO_TENANTS = (
    {
        "slug": "test-tenant-a",
        "tenant_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "webhook_secret": "test-webhook-secret-a",
        "admin_email": "admin-a@example.com",
        "admin_password": "password123",
    },
    {
        "slug": "test-tenant-b",
        "tenant_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "webhook_secret": "test-webhook-secret-b",
        "admin_email": "admin-b@example.com",
        "admin_password": "password123",
    },
)

DEMO_SUPPORT_CASES = (
    {
        "case_type": "normal",
        "message_id": "sample-normal-01",
        "fixture_file": "load_tests/fixtures/sample_messages.jsonl",
    },
    {
        "case_type": "risky",
        "message_id": "sample-risky-01",
        "fixture_file": "load_tests/fixtures/sample_messages.jsonl",
    },
    {
        "case_type": "adversarial",
        "message_id": "sample-adversarial-01",
        "fixture_file": "load_tests/fixtures/sample_messages.jsonl",
    },
    {
        "case_type": "low_confidence",
        "message_id": "sample-low-confidence-01",
        "fixture_file": "load_tests/fixtures/sample_messages.jsonl",
    },
    {
        "case_type": "duplicate",
        "message_id": "sample-duplicate-01",
        "fixture_file": "load_tests/fixtures/sample_messages.jsonl",
    },
)


def _normalize_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


async def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for seed script")

    sql = (Path(__file__).resolve().parents[1] / "docker" / "seed.sql").read_text(encoding="utf-8")
    conn = await asyncpg.connect(_normalize_url(database_url))
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
