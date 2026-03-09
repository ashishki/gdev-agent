"""Apply docker seed SQL against configured Postgres."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import asyncpg


def _normalize_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


async def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for seed script")

    sql = (Path(__file__).resolve().parents[1] / "docker" / "seed.sql").read_text(
        encoding="utf-8"
    )
    conn = await asyncpg.connect(_normalize_url(database_url))
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
