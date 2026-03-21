"""Admin CLI for tenant and RCA operations."""

from __future__ import annotations

import asyncio
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import click
from redis import asyncio as redis_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings, get_settings  # noqa: E402
from app.db import _set_tenant_ctx, make_engine, make_session_factory  # noqa: E402


def _get_settings() -> Settings:
    return get_settings()


def _session_bundle_from_settings(
    settings: Settings,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = make_engine(settings)
    return engine, make_session_factory(engine)


def _redis_client_from_settings(settings: Settings):
    return redis_asyncio.from_url(settings.redis_url, decode_responses=True)


async def _close_redis(redis_client: object) -> None:
    aclose = getattr(redis_client, "aclose", None)
    if callable(aclose):
        await aclose()


async def _invalidate_tenant_cache(redis_client: object, tenant_id: UUID) -> None:
    delete = getattr(redis_client, "delete", None)
    if callable(delete):
        await delete(f"tenant:{tenant_id}:config")


async def _list_tenants(settings: Settings) -> list[dict[str, object]]:
    engine, session_factory = _session_bundle_from_settings(settings)
    try:
        async with session_factory() as session:
            result = await session.execute(
                # admin query - no tenant context needed.
                text(
                    """
                    SELECT tenant_id, name, slug, daily_budget_usd, is_active
                    FROM tenants
                    ORDER BY created_at DESC
                    """
                ),
                {},
            )
            return [dict(row) for row in result.mappings().all()]
    finally:
        await engine.dispose()


async def _create_tenant(
    settings: Settings,
    *,
    name: str,
    slug: str,
    daily_budget_usd: Decimal,
) -> dict[str, object]:
    engine, session_factory = _session_bundle_from_settings(settings)
    redis_client = _redis_client_from_settings(settings)
    tenant_id = uuid4()
    try:
        async with session_factory() as session:
            async with session.begin():
                await _set_tenant_ctx(session, str(tenant_id))
                result = await session.execute(
                    text(
                        """
                        INSERT INTO tenants (tenant_id, name, slug, daily_budget_usd)
                        VALUES (:tenant_id, :name, :slug, :daily_budget_usd)
                        RETURNING tenant_id, name, slug, daily_budget_usd, is_active
                        """
                    ),
                    {
                        "tenant_id": str(tenant_id),
                        "name": name,
                        "slug": slug,
                        "daily_budget_usd": daily_budget_usd,
                    },
                )
                row = result.mappings().one()
        await _invalidate_tenant_cache(redis_client, UUID(str(row["tenant_id"])))
        return dict(row)
    finally:
        await _close_redis(redis_client)
        await engine.dispose()


async def _disable_tenant(settings: Settings, tenant_id: UUID) -> bool:
    engine, session_factory = _session_bundle_from_settings(settings)
    redis_client = _redis_client_from_settings(settings)
    try:
        async with session_factory() as session:
            async with session.begin():
                await _set_tenant_ctx(session, str(tenant_id))
                result = await session.execute(
                    text(
                        """
                        UPDATE tenants
                        SET is_active = FALSE, updated_at = NOW()
                        WHERE tenant_id = :tenant_id
                        RETURNING tenant_id
                        """
                    ),
                    {"tenant_id": str(tenant_id)},
                )
                row = result.mappings().first()
        if row is None:
            return False
        await _invalidate_tenant_cache(redis_client, tenant_id)
        return True
    finally:
        await _close_redis(redis_client)
        await engine.dispose()


async def _budget_status(settings: Settings, tenant_id: UUID) -> SimpleNamespace:
    engine, session_factory = _session_bundle_from_settings(settings)
    try:
        async with session_factory() as session:
            async with session.begin():
                await _set_tenant_ctx(session, str(tenant_id))
                result = await session.execute(
                    text(
                        """
                        SELECT
                            t.daily_budget_usd AS budget_usd,
                            COALESCE(cl.cost_usd, 0) AS current_usd
                        FROM tenants t
                        LEFT JOIN cost_ledger cl
                          ON cl.tenant_id = t.tenant_id
                         AND cl.date = CURRENT_DATE
                        WHERE t.tenant_id = :tenant_id
                        """
                    ),
                    {"tenant_id": str(tenant_id)},
                )
                row = result.mappings().one_or_none()
    finally:
        await engine.dispose()

    if row is None:
        raise click.ClickException(f"Tenant not found: {tenant_id}")

    budget_usd = Decimal(str(row["budget_usd"]))
    current_usd = Decimal(str(row["current_usd"]))
    return SimpleNamespace(
        budget_usd=budget_usd,
        current_usd=current_usd,
        status="exhausted" if current_usd >= budget_usd else "ok",
    )


async def _reset_budget(settings: Settings, tenant_id: UUID) -> int:
    engine, session_factory = _session_bundle_from_settings(settings)
    try:
        async with session_factory() as session:
            async with session.begin():
                await _set_tenant_ctx(session, str(tenant_id))
                result = await session.execute(
                    text(
                        """
                        DELETE FROM cost_ledger
                        WHERE tenant_id = :tenant_id AND date = CURRENT_DATE
                        RETURNING tenant_id
                        """
                    ),
                    {"tenant_id": str(tenant_id)},
                )
                rows = result.mappings().all()
                return len(rows)
    finally:
        await engine.dispose()


async def _run_rca_for_tenant(settings: Settings, tenant_id: UUID) -> None:
    from app.jobs.rca_clusterer import RCAClusterer

    engine, session_factory = _session_bundle_from_settings(settings)
    clusterer = RCAClusterer(settings=settings, db_session_factory=session_factory)
    try:
        await clusterer.run_tenant(str(tenant_id))
    finally:
        await clusterer.aclose()
        await engine.dispose()


@click.group()
def app() -> None:
    """gdev-admin operational CLI."""


@app.group()
def tenant() -> None:
    """Tenant operations."""


@tenant.command("list")
def tenant_list() -> None:
    """List tenants."""
    rows = asyncio.run(_list_tenants(_get_settings()))
    if not rows:
        click.echo("No tenants found.")
        return
    for row in rows:
        click.echo(
            f"{row['tenant_id']} slug={row['slug']} "
            f"active={row['is_active']} budget={row['daily_budget_usd']}"
        )


@tenant.command("create")
@click.option("--name", required=True, type=str)
@click.option("--slug", required=True, type=str)
@click.option("--daily-budget-usd", default=Decimal("10.0"), type=Decimal)
def tenant_create(name: str, slug: str, daily_budget_usd: Decimal) -> None:
    """Create a tenant."""
    row = asyncio.run(
        _create_tenant(
            _get_settings(),
            name=name,
            slug=slug,
            daily_budget_usd=daily_budget_usd,
        )
    )
    click.echo(f"Created tenant {row['tenant_id']} slug={row['slug']}")


@tenant.command("disable")
@click.argument("tenant_id", type=click.UUID)
def tenant_disable(tenant_id: UUID) -> None:
    """Disable a tenant."""
    disabled = asyncio.run(_disable_tenant(_get_settings(), tenant_id))
    if not disabled:
        raise click.ClickException(f"Tenant not found: {tenant_id}")
    click.echo(f"Disabled tenant {tenant_id}")


@app.group()
def budget() -> None:
    """Budget operations."""


@budget.command("check")
@click.argument("tenant_id", type=click.UUID)
def budget_check(tenant_id: UUID) -> None:
    """Check today's tenant budget usage."""
    status = asyncio.run(_budget_status(_get_settings(), tenant_id))
    click.echo(
        f"tenant_id={tenant_id} current_usd={status.current_usd} "
        f"budget_usd={status.budget_usd} status={status.status}"
    )


@budget.command("reset")
@click.argument("tenant_id", type=click.UUID)
def budget_reset(tenant_id: UUID) -> None:
    """Reset today's tenant budget usage."""
    deleted_rows = asyncio.run(_reset_budget(_get_settings(), tenant_id))
    click.echo(f"Reset budget for {tenant_id}; removed_rows={deleted_rows}")


@app.group()
def rca() -> None:
    """RCA operations."""


@rca.command("run")
@click.argument("tenant_id", type=click.UUID)
def rca_run(tenant_id: UUID) -> None:
    """Run RCA clustering for a tenant."""
    asyncio.run(_run_rca_for_tenant(_get_settings(), tenant_id))
    click.echo(f"RCA run completed for {tenant_id}")


if __name__ == "__main__":
    app()
