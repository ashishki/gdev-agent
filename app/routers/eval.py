"""Eval execution endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.dependencies import require_role
from app.schemas import ErrorDetail, ErrorResponse, EvalRunListResponse, EvalRunTriggerResponse
from app.services.eval_service import EvalService, InvalidCursorError

router = APIRouter()


def _get_eval_service(request: Request) -> EvalService:
    app = getattr(request, "app", None)
    app_state = getattr(app, "state", None)
    return EvalService(db_session_factory=getattr(app_state, "db_session_factory", None))


@router.post("/eval/run")
async def start_eval_run(
    request: Request,
    _: None = require_role("tenant_admin"),
) -> EvalRunTriggerResponse:
    return await _get_eval_service(request).create_run(tenant_id=request.state.tenant_id)


@router.get("/eval/runs", response_model=EvalRunListResponse)
async def list_eval_runs(
    request: Request,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
    _: None = require_role("viewer", "support_agent", "tenant_admin"),
) -> EvalRunListResponse | JSONResponse:
    try:
        return await _get_eval_service(request).get_runs(
            tenant_id=request.state.tenant_id,
            cursor=cursor,
            limit=limit,
            db=db,
        )
    except InvalidCursorError:
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(
                error=ErrorDetail(
                    code="invalid_cursor",
                    message="cursor must be a valid ISO timestamp",
                )
            ).model_dump(mode="json"),
        )
