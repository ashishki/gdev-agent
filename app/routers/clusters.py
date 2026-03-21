"""Cluster read endpoints."""

from __future__ import annotations

import hashlib
from time import perf_counter
from typing import Literal
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram
from pydantic import BaseModel
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
    TicketListItem,
)

router = APIRouter()

try:  # pragma: no cover - optional dependency in minimal local envs
    from opentelemetry import trace  # type: ignore[import-not-found]

    TRACER = trace.get_tracer(__name__)
except Exception:  # pragma: no cover - fallback when opentelemetry is unavailable

    class _NoopSpan:
        def __enter__(self) -> "_NoopSpan":
            return self

        def __exit__(self, exc_type, exc, tb) -> Literal[False]:
            return False

        def set_attribute(self, _name: str, _value: object) -> None:
            return None

        def record_exception(self, _exc: BaseException) -> None:
            return None

    class _NoopTracer:
        def start_as_current_span(self, _name: str) -> _NoopSpan:
            return _NoopSpan()

    TRACER = _NoopTracer()

CLUSTER_TICKETS_REQUESTS_TOTAL = Counter(
    "gdev_cluster_tickets_requests_total",
    "Cluster ticket list requests by outcome",
    ["tenant_hash", "outcome"],
)
CLUSTER_TICKETS_DURATION_SECONDS = Histogram(
    "gdev_cluster_tickets_duration_seconds",
    "Cluster ticket list request latency",
    ["tenant_hash"],
)
CLUSTER_LIST_REQUESTS_TOTAL = Counter(
    "gdev_cluster_list_requests_total",
    "Cluster list requests by outcome",
    ["tenant_hash", "outcome"],
)
CLUSTER_LIST_DURATION_SECONDS = Histogram(
    "gdev_cluster_list_duration_seconds",
    "Cluster list request latency",
    ["tenant_hash"],
)
CLUSTER_DETAIL_REQUESTS_TOTAL = Counter(
    "gdev_cluster_detail_requests_total",
    "Cluster detail requests by outcome",
    ["tenant_hash", "outcome"],
)
CLUSTER_DETAIL_DURATION_SECONDS = Histogram(
    "gdev_cluster_detail_duration_seconds",
    "Cluster detail request latency",
    ["tenant_hash"],
)


def _sha256_short(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


class ClusterTicketsResponse(BaseModel):
    tickets: list[TicketListItem]
    total: int
    page: int


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
    tenant_id = str(request.state.tenant_id)
    tenant_hash = _sha256_short(tenant_id)
    started_at = perf_counter()

    with TRACER.start_as_current_span("router.clusters.list_clusters") as span:
        span.set_attribute("tenant_id_hash", tenant_hash)
        span.set_attribute("limit", limit)
        try:
            parsed_cursor = _parse_cursor(cursor)
            if isinstance(parsed_cursor, JSONResponse):
                CLUSTER_LIST_REQUESTS_TOTAL.labels(
                    tenant_hash=tenant_hash, outcome="invalid_cursor"
                ).inc()
                return parsed_cursor

            params: dict[str, object] = {
                "tenant_id": tenant_id,
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
            CLUSTER_LIST_REQUESTS_TOTAL.labels(
                tenant_hash=tenant_hash, outcome="success"
            ).inc()
            return ClusterListResponse(data=data, cursor=next_cursor, total=None)
        except Exception as exc:
            CLUSTER_LIST_REQUESTS_TOTAL.labels(
                tenant_hash=tenant_hash, outcome="error"
            ).inc()
            span.record_exception(exc)
            raise
        finally:
            CLUSTER_LIST_DURATION_SECONDS.labels(tenant_hash=tenant_hash).observe(
                perf_counter() - started_at
            )


@router.get("/clusters/{cluster_id}", response_model=ClusterDetailResponse)
async def get_cluster(
    cluster_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    _: None = require_role("viewer", "support_agent", "tenant_admin"),
) -> ClusterDetailResponse | JSONResponse:
    """Fetch cluster details plus up to 10 member ticket IDs."""
    tenant_id = str(request.state.tenant_id)
    tenant_hash = _sha256_short(tenant_id)
    started_at = perf_counter()

    with TRACER.start_as_current_span("router.clusters.get_cluster") as span:
        span.set_attribute("tenant_id_hash", tenant_hash)
        span.set_attribute("cluster_id", str(cluster_id))
        try:
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
                            "tenant_id": tenant_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                CLUSTER_DETAIL_REQUESTS_TOTAL.labels(
                    tenant_hash=tenant_hash, outcome="not_found"
                ).inc()
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
                        FROM rca_cluster_members
                        WHERE cluster_id = :cluster_id
                        ORDER BY created_at DESC, ticket_id DESC
                        LIMIT 10
                        """
                        ),
                        {"cluster_id": str(cluster_id)},
                    )
                )
                .mappings()
                .all()
            )
            detail = dict(row)
            detail["ticket_ids"] = [item["ticket_id"] for item in ticket_rows[:10]]
            CLUSTER_DETAIL_REQUESTS_TOTAL.labels(
                tenant_hash=tenant_hash, outcome="success"
            ).inc()
            return ClusterDetailResponse(
                data=[ClusterDetailItem.model_validate(detail)], cursor=None, total=None
            )
        except Exception as exc:
            CLUSTER_DETAIL_REQUESTS_TOTAL.labels(
                tenant_hash=tenant_hash, outcome="error"
            ).inc()
            span.record_exception(exc)
            raise
        finally:
            CLUSTER_DETAIL_DURATION_SECONDS.labels(tenant_hash=tenant_hash).observe(
                perf_counter() - started_at
            )


@router.get("/clusters/{cluster_id}/tickets", response_model=ClusterTicketsResponse)
async def get_cluster_tickets(
    cluster_id: UUID,
    request: Request,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
    _: None = require_role("viewer", "support_agent", "tenant_admin"),
) -> ClusterTicketsResponse | JSONResponse:
    """Fetch paginated tickets for a tenant cluster."""
    tenant_id = str(request.state.tenant_id)
    tenant_hash = _sha256_short(tenant_id)
    started_at = perf_counter()

    with TRACER.start_as_current_span("router.clusters.get_cluster_tickets") as span:
        span.set_attribute("tenant_id_hash", tenant_hash)
        span.set_attribute("page", page)
        try:
            cluster_row = (
                (
                    await db.execute(
                        text(
                            """
                            SELECT cluster_id
                            FROM cluster_summaries
                            WHERE cluster_id = :cluster_id AND tenant_id = :tenant_id
                            LIMIT 1
                            """
                        ),
                        {"cluster_id": str(cluster_id), "tenant_id": tenant_id},
                    )
                )
                .mappings()
                .first()
            )
            if cluster_row is None:
                CLUSTER_TICKETS_REQUESTS_TOTAL.labels(
                    tenant_hash=tenant_hash, outcome="not_found"
                ).inc()
                return JSONResponse(
                    status_code=404,
                    content=ErrorResponse(
                        error=ErrorDetail(
                            code="cluster_not_found",
                            message="Cluster not found",
                        )
                    ).model_dump(mode="json"),
                )

            total = int(
                (
                    await db.execute(
                        text(
                            """
                            SELECT COUNT(*) AS total
                            FROM rca_cluster_members AS m
                            JOIN tickets AS t ON t.ticket_id = m.ticket_id
                            WHERE m.cluster_id = :cluster_id AND t.tenant_id = :tenant_id
                            """
                        ),
                        {"cluster_id": str(cluster_id), "tenant_id": tenant_id},
                    )
                )
                .mappings()
                .first()["total"]
            )
            rows = (
                (
                    await db.execute(
                        text(
                            """
                            SELECT
                                t.ticket_id,
                                t.message_id,
                                t.platform,
                                t.game_title,
                                t.created_at
                            FROM rca_cluster_members AS m
                            JOIN tickets AS t ON t.ticket_id = m.ticket_id
                            WHERE m.cluster_id = :cluster_id AND t.tenant_id = :tenant_id
                            ORDER BY t.created_at DESC, t.ticket_id DESC
                            LIMIT :limit
                            OFFSET :offset
                            """
                        ),
                        {
                            "cluster_id": str(cluster_id),
                            "tenant_id": tenant_id,
                            "limit": limit,
                            "offset": (page - 1) * limit,
                        },
                    )
                )
                .mappings()
                .all()
            )

            CLUSTER_TICKETS_REQUESTS_TOTAL.labels(
                tenant_hash=tenant_hash, outcome="success"
            ).inc()
            return ClusterTicketsResponse(
                tickets=[TicketListItem.model_validate(dict(row)) for row in rows],
                total=total,
                page=page,
            )
        except Exception as exc:
            span.record_exception(exc)
            CLUSTER_TICKETS_REQUESTS_TOTAL.labels(
                tenant_hash=tenant_hash, outcome="error"
            ).inc()
            raise
        finally:
            CLUSTER_TICKETS_DURATION_SECONDS.labels(tenant_hash=tenant_hash).observe(
                perf_counter() - started_at
            )
