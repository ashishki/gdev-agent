"""Eval execution endpoints."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Request
from sqlalchemy import text

from app.dependencies import require_role
from app.schemas import EvalRunTriggerResponse
from eval.runner import run_eval_job

LOGGER = logging.getLogger(__name__)
router = APIRouter()


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
