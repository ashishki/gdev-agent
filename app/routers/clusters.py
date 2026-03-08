"""Cluster read endpoints."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.dependencies import require_role
from app.schemas import (
    ClusterDetailItem,
    ClusterDetailResponse,
    ClusterListItem,
    ClusterListResponse,
    ErrorDetail,
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
                error=ErrorDetail(
                    code="invalid_cursor",
                    message="cursor must be a valid ISO timestamp",
                )
            ).model_dump(mode="json"),
        )


@router.get("/clusters", response_model=ClusterListResponse)
async def list_clusters(
    request: Request,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    is_active: bool | None = Query(default=True),
    severity: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
    _: None = require_role("viewer", "support_agent", "tenant_admin"),
) -> ClusterListResponse | JSONResponse:
    """List RCA clusters for current tenant."""
    parsed_cursor = _parse_cursor(cursor)
    if isinstance(parsed_cursor, JSONResponse):
        return parsed_cursor

    params: dict[str, object] = {
        "tenant_id": str(request.state.tenant_id),
        "limit": limit + 1,
        "is_active": is_active,
        "severity": severity,
        "cursor": parsed_cursor,
    }
    rows = (
        (
            await db.execute(
                text(
                    """
                SELECT
                    cluster_id,
                    label,
                    summary,
                    ticket_count,
                    severity,
                    first_seen,
                    last_seen,
                    is_active,
                    updated_at
                FROM cluster_summaries
                WHERE tenant_id = :tenant_id
                  AND (:is_active IS NULL OR is_active = :is_active)
                  AND (:severity IS NULL OR severity = :severity)
                  AND (:cursor IS NULL OR updated_at < :cursor)
                ORDER BY updated_at DESC
                LIMIT :limit
                """
                ),
                params,
            )
        )
        .mappings()
        .all()
    )

    page_rows = rows[:limit]
    data = [ClusterListItem.model_validate(dict(row)) for row in page_rows]
    next_cursor = data[-1].updated_at.isoformat() if len(rows) > limit else None
    return ClusterListResponse(data=data, cursor=next_cursor, total=None)


@router.get("/clusters/{cluster_id}", response_model=ClusterDetailResponse)
async def get_cluster(
    cluster_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    _: None = require_role("viewer", "support_agent", "tenant_admin"),
) -> ClusterDetailResponse | JSONResponse:
    """Fetch cluster details plus up to 10 member ticket IDs."""
    row = (
        (
            await db.execute(
                text(
                    """
                SELECT
                    cluster_id,
                    label,
                    summary,
                    ticket_count,
                    severity,
                    first_seen,
                    last_seen,
                    is_active,
                    updated_at
                FROM cluster_summaries
                WHERE cluster_id = :cluster_id AND tenant_id = :tenant_id
                LIMIT 1
                """
                ),
                {
                    "cluster_id": str(cluster_id),
                    "tenant_id": str(request.state.tenant_id),
                },
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error=ErrorDetail(
                    code="cluster_not_found",
                    message="Cluster not found",
                )
            ).model_dump(mode="json"),
        )

    ticket_rows = (
        (
            await db.execute(
                text(
                    """
                SELECT ticket_id
                FROM ticket_embeddings
                WHERE
                    tenant_id = :tenant_id
                    AND created_at >= COALESCE(:first_seen, created_at)
                    AND created_at <= COALESCE(:last_seen, created_at)
                ORDER BY created_at DESC
                LIMIT 10
                """
                ),
                {
                    "tenant_id": str(request.state.tenant_id),
                    "first_seen": row["first_seen"],
                    "last_seen": row["last_seen"],
                },
            )
        )
        .mappings()
        .all()
    )
    detail = dict(row)
    detail["ticket_ids"] = [item["ticket_id"] for item in ticket_rows[:10]]
    return ClusterDetailResponse(
        data=[ClusterDetailItem.model_validate(detail)], cursor=None, total=None
    )
