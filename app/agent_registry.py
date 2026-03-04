"""Agent config registry service."""

from __future__ import annotations

import hashlib
import json
import logging
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas import AgentConfigItem, AgentConfigUpdate

LOGGER = logging.getLogger(__name__)


class AgentConfigNotFoundError(Exception):
    """Raised when an agent config cannot be found for a tenant."""


class AgentRegistryService:
    """Service for reading and updating tenant agent configs."""

    async def update_config(
        self,
        *,
        tenant_id: UUID,
        agent_config_id: UUID,
        payload: AgentConfigUpdate,
        db: AsyncSession,
    ) -> AgentConfigItem:
        """Version-bump and replace an agent config for a tenant."""
        current_row = (
            await db.execute(
                text(
                    """
                    SELECT agent_config_id, version
                    FROM agent_configs
                    WHERE agent_config_id = :agent_config_id
                      AND tenant_id = :tenant_id
                      AND is_current = TRUE
                    LIMIT 1
                    """
                ),
                {"agent_config_id": str(agent_config_id), "tenant_id": str(tenant_id)},
            )
        ).mappings().first()
        if current_row is None:
            raise AgentConfigNotFoundError(f"Agent config {agent_config_id} not found")

        old_version = int(current_row["version"])
        new_version = old_version + 1

        await db.execute(
            text(
                """
                UPDATE agent_configs
                SET is_current = FALSE
                WHERE agent_config_id = :agent_config_id
                  AND tenant_id = :tenant_id
                """
            ),
            {"agent_config_id": str(agent_config_id), "tenant_id": str(tenant_id)},
        )

        inserted_row = (
            await db.execute(
                text(
                    """
                    INSERT INTO agent_configs (
                        tenant_id,
                        agent_name,
                        version,
                        model_id,
                        max_turns,
                        tools_enabled,
                        guardrails,
                        prompt_version,
                        is_current
                    )
                    VALUES (
                        :tenant_id,
                        :agent_name,
                        :version,
                        :model_id,
                        :max_turns,
                        :tools_enabled,
                        CAST(:guardrails AS jsonb),
                        :prompt_version,
                        TRUE
                    )
                    RETURNING
                        agent_config_id,
                        agent_name,
                        version,
                        model_id,
                        max_turns,
                        tools_enabled,
                        guardrails,
                        prompt_version,
                        is_current,
                        created_at
                    """
                ),
                {
                    "tenant_id": str(tenant_id),
                    "agent_name": payload.agent_name,
                    "version": new_version,
                    "model_id": payload.model_id,
                    "max_turns": payload.max_turns,
                    "tools_enabled": payload.tools_enabled,
                    "guardrails": json.dumps(payload.guardrails, ensure_ascii=False),
                    "prompt_version": payload.prompt_version,
                },
            )
        ).mappings().one()

        tenant_id_hash = hashlib.sha256(str(tenant_id).encode("utf-8")).hexdigest()[:16]
        LOGGER.info(
            "agent config updated",
            extra={
                "event": "agent_config_updated",
                "context": {
                    "tenant_id_hash": tenant_id_hash,
                    "old_version": old_version,
                    "new_version": new_version,
                },
            },
        )
        return AgentConfigItem.model_validate(dict(inserted_row))
