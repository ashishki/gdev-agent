from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Read DATABASE_URL directly from the environment to preserve the full driver
# string (e.g. "postgresql+asyncpg://...").  Pydantic's PostgresDsn normalises
# the scheme and strips the "+asyncpg" suffix, which breaks SQLAlchemy's async
# engine selection.
_database_url = os.environ.get("DATABASE_URL")
if not _database_url:
    raise ValueError("DATABASE_URL environment variable is required for alembic migrations")

config.set_main_option("sqlalchemy.url", _database_url)

target_metadata = None


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    # Create the engine directly from the URL to avoid async_engine_from_config
    # falling back to the psycopg2 dialect when the URL was set via set_main_option
    # rather than being present in the INI file on disk.
    connectable = create_async_engine(_database_url, poolclass=pool.NullPool)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    import asyncio

    asyncio.run(run_migrations_online())
