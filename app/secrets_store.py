"""Secure webhook secret lookup from Postgres."""

from __future__ import annotations

from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.tenant_registry import TenantNotFoundError


class WebhookSecretNotFoundError(Exception):
    """Raised when no active webhook secret exists for a tenant."""


class WebhookSecretStore:
    """Retrieves per-tenant webhook secrets from Postgres."""

    def __init__(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        encryption_key: str,
    ) -> None:
        self._db_session_factory = db_session_factory
        self._fernet = Fernet(encryption_key.encode("utf-8"))

    async def get_secret(self, tenant_id: UUID) -> str:
        async with self._db_session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT secret_ciphertext
                    FROM webhook_secrets
                    WHERE tenant_id = :tenant_id
                      AND is_active = TRUE
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"tenant_id": str(tenant_id)},
            )
            row = result.mappings().first()

        if row is None:
            raise WebhookSecretNotFoundError(
                f"No active webhook secret for tenant {tenant_id}"
            )

        ciphertext = row["secret_ciphertext"]
        if isinstance(ciphertext, str):
            token = ciphertext.encode("utf-8")
        else:
            token = bytes(ciphertext)
        try:
            return self._fernet.decrypt(token).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise WebhookSecretNotFoundError(
                "Unable to decrypt webhook secret"
            ) from exc

    async def get_secret_by_slug(self, tenant_slug: str) -> str:
        tenant_id, secret = await self.get_secret_and_tenant_by_slug(tenant_slug)
        _ = tenant_id
        return secret

    async def get_secret_and_tenant_by_slug(self, tenant_slug: str) -> tuple[UUID, str]:
        async with self._db_session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT tenant_id
                    FROM tenants
                    WHERE slug = :slug
                      AND is_active = TRUE
                    """
                ),
                {"slug": tenant_slug},
            )
            row = result.mappings().first()

        if row is None:
            raise TenantNotFoundError(f"Tenant {tenant_slug} not found")

        tenant_id = UUID(str(row["tenant_id"]))
        return tenant_id, await self.get_secret(tenant_id)
