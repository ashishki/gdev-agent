"""Agent registry read endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.dependencies import require_role
from app.schemas import AgentConfigItem, AgentListResponse, ErrorResponse

router = APIRouter()


def _parse_cursor(cursor: str | None):
    if cursor is None:
        return None
    try:
        return datetime.fromisoformat(cursor)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(
                error={"code": "invalid_cursor", "message": "cursor must be a valid ISO timestamp"}
            ).model_dump(mode="json"),
        )


@router.get("/agents", response_model=AgentListResponse)
async def list_agents(
    request: Request,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
    _: None = require_role("tenant_admin"),
) -> AgentListResponse | JSONResponse:
    """List current tenant agent configs."""
    parsed_cursor = _parse_cursor(cursor)
    if isinstance(parsed_cursor, JSONResponse):
        return parsed_cursor

    if parsed_cursor is None:
        statement = text(
            """
            SELECT
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
            FROM agent_configs
            WHERE tenant_id = :tenant_id
            ORDER BY created_at DESC
            LIMIT :limit
            """
        )
        params = {"tenant_id": str(request.state.tenant_id), "limit": limit + 1}
    else:
        statement = text(
            """
            SELECT
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
            FROM agent_configs
            WHERE tenant_id = :tenant_id AND created_at < :cursor
            ORDER BY created_at DESC
            LIMIT :limit
            """
        )
        params = {
            "tenant_id": str(request.state.tenant_id),
            "cursor": parsed_cursor,
            "limit": limit + 1,
        }

    rows = (await db.execute(statement, params)).mappings().all()
    page_rows = rows[:limit]
    data = [AgentConfigItem.model_validate(dict(row)) for row in page_rows]
    next_cursor = data[-1].created_at.isoformat() if len(rows) > limit else None
    return AgentListResponse(data=data, cursor=next_cursor, total=None)
