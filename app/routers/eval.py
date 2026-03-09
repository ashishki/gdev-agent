"""Eval execution endpoints."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.dependencies import require_role
from app.schemas import ErrorResponse, EvalRunItem, EvalRunListResponse, EvalRunTriggerResponse
from eval.runner import run_eval_job

LOGGER = logging.getLogger(__name__)
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


async def _run_eval_background(
    *,
    request: Request,
    tenant_id: UUID,
    eval_run_id: UUID,
) -> None:
    session_factory = request.app.state.db_session_factory
    cases_path = Path(__file__).resolve().parents[2] / "eval" / "cases.jsonl"
    try:
        async with session_factory() as session:
            await run_eval_job(
                cases_path=cases_path,
                tenant_id=tenant_id,
                eval_run_id=eval_run_id,
                db_session=session,
                agent=None,
            )
    except Exception:
        LOGGER.error(
            "eval run failed",
            extra={
                "event": "eval_run_failed",
                "context": {"tenant_id": str(tenant_id), "eval_run_id": str(eval_run_id)},
            },
            exc_info=True,
        )
        async with session_factory() as session:
            async with session.begin():
                await session.execute(
                    text("SET LOCAL app.current_tenant_id = :tid"),
                    {"tid": str(tenant_id)},
                )
                await session.execute(
                    text(
                        """
                        UPDATE eval_runs
                        SET status = :status
                        WHERE eval_run_id = :eval_run_id AND tenant_id = :tenant_id
                        """
                    ),
                    {
                        "status": "failed",
                        "eval_run_id": str(eval_run_id),
                        "tenant_id": str(tenant_id),
                    },
                )


@router.post("/eval/run")
async def start_eval_run(
    request: Request,
    _: None = require_role("tenant_admin"),
) -> EvalRunTriggerResponse:
    """Queue an asynchronous eval run and return its id."""
    tenant_id = request.state.tenant_id
    eval_run_id = uuid4()
    async with request.app.state.db_session_factory() as session:
        async with session.begin():
            await session.execute(
                text("SET LOCAL app.current_tenant_id = :tid"),
                {"tid": str(tenant_id)},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO eval_runs (eval_run_id, tenant_id, status)
                    VALUES (:eval_run_id, :tenant_id, :status)
                    """
                ),
                {
                    "eval_run_id": str(eval_run_id),
                    "tenant_id": str(tenant_id),
                    "status": "queued",
                },
            )
    asyncio.create_task(
        _run_eval_background(
            request=request,
            tenant_id=tenant_id,
            eval_run_id=eval_run_id,
        )
    )
    return EvalRunTriggerResponse(eval_run_id=eval_run_id)


@router.get("/eval/runs", response_model=EvalRunListResponse)
async def list_eval_runs(
    request: Request,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
    _: None = require_role("viewer", "support_agent", "tenant_admin"),
) -> EvalRunListResponse | JSONResponse:
    """List eval run history for the current tenant."""
    parsed_cursor = _parse_cursor(cursor)
    if isinstance(parsed_cursor, JSONResponse):
        return parsed_cursor

    if parsed_cursor is None:
        statement = text(
            """
            SELECT
                eval_run_id,
                started_at,
                completed_at,
                f1_score,
                guard_block_rate,
                cost_usd,
                status,
                created_at
            FROM eval_runs
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
                eval_run_id,
                started_at,
                completed_at,
                f1_score,
                guard_block_rate,
                cost_usd,
                status,
                created_at
            FROM eval_runs
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
    data = [EvalRunItem.model_validate(dict(row)) for row in page_rows]
    next_cursor = data[-1].created_at.isoformat() if len(rows) > limit else None
    return EvalRunListResponse(data=data, cursor=next_cursor, total=None)
