"""Analytics and audit read endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.dependencies import require_role
from app.schemas import (
    AuditListItem,
    AuditListResponse,
    CostMetricItem,
    CostMetricResponse,
    ErrorResponse,
)

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


@router.get("/audit", response_model=AuditListResponse)
async def list_audit(
    request: Request,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
    _: None = require_role("tenant_admin"),
) -> AuditListResponse | JSONResponse:
    """List audit entries newest-first for the current tenant."""
    parsed_cursor = _parse_cursor(cursor)
    if isinstance(parsed_cursor, JSONResponse):
        return parsed_cursor

    if parsed_cursor is None:
        statement = text(
            """
            SELECT
                audit_id,
                request_id,
                message_id,
                category,
                urgency,
                confidence,
                action_tool,
                status,
                ticket_id,
                latency_ms,
                input_tokens,
                output_tokens,
                cost_usd,
                created_at
            FROM audit_log
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
                audit_id,
                request_id,
                message_id,
                category,
                urgency,
                confidence,
                action_tool,
                status,
                ticket_id,
                latency_ms,
                input_tokens,
                output_tokens,
                cost_usd,
                created_at
            FROM audit_log
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
    data = [AuditListItem.model_validate(dict(row)) for row in page_rows]
    next_cursor = data[-1].created_at.isoformat() if len(rows) > limit else None
    return AuditListResponse(data=data, cursor=next_cursor, total=None)


@router.get("/metrics/cost", response_model=CostMetricResponse)
async def list_cost_metrics(
    request: Request,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
    _: None = require_role("tenant_admin"),
) -> CostMetricResponse | JSONResponse:
    """List per-day cost ledger rows for the current tenant."""
    parsed_cursor = _parse_cursor(cursor)
    if isinstance(parsed_cursor, JSONResponse):
        return parsed_cursor

    if parsed_cursor is None:
        statement = text(
            """
            SELECT
                ledger_id,
                date,
                input_tokens,
                output_tokens,
                cost_usd,
                request_count,
                created_at
            FROM cost_ledger
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
                ledger_id,
                date,
                input_tokens,
                output_tokens,
                cost_usd,
                request_count,
                created_at
            FROM cost_ledger
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
    data = [CostMetricItem.model_validate(dict(row)) for row in page_rows]
    next_cursor = data[-1].created_at.isoformat() if len(rows) > limit else None
    return CostMetricResponse(data=data, cursor=next_cursor, total=None)
