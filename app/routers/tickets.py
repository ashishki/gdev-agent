"""Ticket read endpoints."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.dependencies import require_role
from app.schemas import ErrorResponse, TicketDetailResponse, TicketListItem, TicketListResponse

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


@router.get("/tickets", response_model=TicketListResponse)
async def list_tickets(
    request: Request,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
    _: None = require_role("viewer", "support_agent", "tenant_admin"),
) -> TicketListResponse | JSONResponse:
    """List tenant tickets with cursor pagination."""
    parsed_cursor = _parse_cursor(cursor)
    if isinstance(parsed_cursor, JSONResponse):
        return parsed_cursor

    if parsed_cursor is None:
        statement = text(
            """
            SELECT ticket_id, message_id, platform, game_title, created_at
            FROM tickets
            WHERE tenant_id = :tenant_id
            ORDER BY created_at DESC
            LIMIT :limit
            """
        )
        params = {"tenant_id": str(request.state.tenant_id), "limit": limit + 1}
    else:
        statement = text(
            """
            SELECT ticket_id, message_id, platform, game_title, created_at
            FROM tickets
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
    data = [TicketListItem.model_validate(dict(row)) for row in page_rows]
    next_cursor = data[-1].created_at.isoformat() if len(rows) > limit else None
    return TicketListResponse(data=data, cursor=next_cursor, total=None)


@router.get("/tickets/{ticket_id}", response_model=TicketDetailResponse)
async def get_ticket(
    ticket_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    _: None = require_role("viewer", "support_agent", "tenant_admin"),
) -> TicketDetailResponse | JSONResponse:
    """Fetch a single tenant ticket by id."""
    row = (
        await db.execute(
            text(
                """
                SELECT
                    t.ticket_id,
                    t.message_id,
                    t.platform,
                    t.game_title,
                    t.raw_text,
                    t.created_at,
                    c.category,
                    c.urgency,
                    c.confidence,
                    a.action_tool,
                    a.status
                FROM tickets AS t
                LEFT JOIN LATERAL (
                    SELECT category, urgency, confidence
                    FROM ticket_classifications
                    WHERE ticket_id = t.ticket_id AND tenant_id = :tenant_id
                    ORDER BY created_at DESC
                    LIMIT 1
                ) AS c ON TRUE
                LEFT JOIN LATERAL (
                    SELECT action_tool, status
                    FROM audit_log
                    WHERE ticket_id = t.ticket_id AND tenant_id = :tenant_id
                    ORDER BY created_at DESC
                    LIMIT 1
                ) AS a ON TRUE
                WHERE t.ticket_id = :ticket_id AND t.tenant_id = :tenant_id
                LIMIT 1
                """
            ),
            {"ticket_id": str(ticket_id), "tenant_id": str(request.state.tenant_id)},
        )
    ).mappings().first()

    if row is None:
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error={"code": "ticket_not_found", "message": "Ticket not found"}
            ).model_dump(mode="json"),
        )

    return TicketDetailResponse(data=[dict(row)], cursor=None, total=None)
