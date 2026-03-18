"""Eval service layer."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Literal
from uuid import UUID, uuid4

from prometheus_client import Counter, Histogram
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.cost_ledger import BudgetExhaustedError, CostLedger
from app.schemas import EvalRunItem, EvalRunListResponse, EvalRunTriggerResponse
from eval.runner import run_eval_job

LOGGER = logging.getLogger(__name__)
EVAL_SERVICE_CALLS_TOTAL = Counter(
    "gdev_eval_service_calls_total",
    "Eval service method calls by outcome",
    ["method", "outcome"],
)
EVAL_SERVICE_DURATION_SECONDS = Histogram(
    "gdev_eval_service_duration_seconds",
    "Eval service method latency",
    ["method"],
)

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


class InvalidCursorError(ValueError):
    """Raised when the eval run cursor cannot be parsed as ISO datetime."""


def _sha256_short(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


class EvalService:
    """Business logic for eval endpoints."""

    def __init__(
        self,
        *,
        db_session_factory,
        cases_path: Path | None = None,
        cost_ledger: CostLedger | None = None,
        eval_runner=run_eval_job,
        task_scheduler=asyncio.create_task,
    ) -> None:
        self._db_session_factory = db_session_factory
        self._cases_path = cases_path or Path(__file__).resolve().parents[2] / "eval" / "cases.jsonl"
        self._cost_ledger = cost_ledger or CostLedger()
        self._eval_runner = eval_runner
        self._task_scheduler = task_scheduler

    async def create_run(self, *, tenant_id: UUID) -> EvalRunTriggerResponse:
        started_at = perf_counter()
        tenant_hash = _sha256_short(str(tenant_id))
        eval_run_id = uuid4()

        with TRACER.start_as_current_span("service.eval.create_run") as span:
            span.set_attribute("tenant_id_hash", tenant_hash)
            span.set_attribute("eval_run_id", str(eval_run_id))
            try:
                async with self._db_session_factory() as session:
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

                try:
                    async with self._db_session_factory() as session:
                        async with session.begin():
                            await session.execute(
                                text("SET LOCAL app.current_tenant_id = :tid"),
                                {"tid": str(tenant_id)},
                            )
                            await self._cost_ledger.check_budget(tenant_id, session)
                except BudgetExhaustedError:
                    async with self._db_session_factory() as session:
                        await self._mark_run_status(
                            session=session,
                            tenant_id=tenant_id,
                            eval_run_id=eval_run_id,
                            status="aborted_budget",
                            completed_at=datetime.now(UTC),
                        )
                    EVAL_SERVICE_CALLS_TOTAL.labels(
                        method="create_run", outcome="budget_blocked"
                    ).inc()
                    LOGGER.info(
                        "eval run budget blocked",
                        extra={
                            "event": "eval_run_budget_blocked",
                            "context": {
                                "tenant_id_hash": tenant_hash,
                                "eval_run_id": str(eval_run_id),
                            },
                        },
                    )
                    return EvalRunTriggerResponse(eval_run_id=eval_run_id)

                self._task_scheduler(
                    self._run_eval_background(
                        tenant_id=tenant_id,
                        eval_run_id=eval_run_id,
                    )
                )
                EVAL_SERVICE_CALLS_TOTAL.labels(
                    method="create_run", outcome="success"
                ).inc()
                LOGGER.info(
                    "eval run queued",
                    extra={
                        "event": "eval_run_queued",
                        "context": {
                            "tenant_id_hash": tenant_hash,
                            "eval_run_id": str(eval_run_id),
                        },
                    },
                )
                return EvalRunTriggerResponse(eval_run_id=eval_run_id)
            except Exception as exc:
                span.record_exception(exc)
                EVAL_SERVICE_CALLS_TOTAL.labels(method="create_run", outcome="error").inc()
                LOGGER.error(
                    "eval run creation failed",
                    extra={
                        "event": "eval_run_creation_failed",
                        "context": {"tenant_id_hash": tenant_hash},
                    },
                    exc_info=True,
                )
                raise
            finally:
                EVAL_SERVICE_DURATION_SECONDS.labels(method="create_run").observe(
                    perf_counter() - started_at
                )

    async def get_runs(
        self,
        *,
        tenant_id: UUID,
        cursor: str | None,
        limit: int,
        db: AsyncSession,
    ) -> EvalRunListResponse:
        started_at = perf_counter()
        tenant_hash = _sha256_short(str(tenant_id))

        with TRACER.start_as_current_span("service.eval.get_runs") as span:
            span.set_attribute("tenant_id_hash", tenant_hash)
            span.set_attribute("limit", limit)
            try:
                parsed_cursor = self._parse_cursor(cursor)
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
                    params = {"tenant_id": str(tenant_id), "limit": limit + 1}
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
                        "tenant_id": str(tenant_id),
                        "cursor": parsed_cursor,
                        "limit": limit + 1,
                    }

                rows = (await db.execute(statement, params)).mappings().all()
                page_rows = rows[:limit]
                data = [EvalRunItem.model_validate(dict(row)) for row in page_rows]
                next_cursor = data[-1].created_at.isoformat() if len(rows) > limit else None
                EVAL_SERVICE_CALLS_TOTAL.labels(method="get_runs", outcome="success").inc()
                LOGGER.info(
                    "eval runs listed",
                    extra={
                        "event": "eval_runs_listed",
                        "context": {"tenant_id_hash": tenant_hash},
                    },
                )
                return EvalRunListResponse(data=data, cursor=next_cursor, total=None)
            except InvalidCursorError:
                EVAL_SERVICE_CALLS_TOTAL.labels(
                    method="get_runs", outcome="invalid_cursor"
                ).inc()
                raise
            except Exception as exc:
                span.record_exception(exc)
                EVAL_SERVICE_CALLS_TOTAL.labels(method="get_runs", outcome="error").inc()
                LOGGER.error(
                    "eval runs lookup failed",
                    extra={
                        "event": "eval_runs_lookup_failed",
                        "context": {"tenant_id_hash": tenant_hash},
                    },
                    exc_info=True,
                )
                raise
            finally:
                EVAL_SERVICE_DURATION_SECONDS.labels(method="get_runs").observe(
                    perf_counter() - started_at
                )

    async def get_run_status(
        self,
        *,
        tenant_id: UUID,
        eval_run_id: UUID,
        db: AsyncSession,
    ) -> EvalRunItem | None:
        started_at = perf_counter()
        tenant_hash = _sha256_short(str(tenant_id))

        with TRACER.start_as_current_span("service.eval.get_run_status") as span:
            span.set_attribute("tenant_id_hash", tenant_hash)
            span.set_attribute("eval_run_id", str(eval_run_id))
            try:
                row = (
                    await db.execute(
                        text(
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
                            WHERE tenant_id = :tenant_id AND eval_run_id = :eval_run_id
                            LIMIT 1
                            """
                        ),
                        {
                            "tenant_id": str(tenant_id),
                            "eval_run_id": str(eval_run_id),
                        },
                    )
                ).mappings().first()
                outcome = "found" if row is not None else "not_found"
                EVAL_SERVICE_CALLS_TOTAL.labels(
                    method="get_run_status", outcome=outcome
                ).inc()
                LOGGER.info(
                    "eval run status fetched",
                    extra={
                        "event": "eval_run_status_fetched",
                        "context": {
                            "tenant_id_hash": tenant_hash,
                            "eval_run_id": str(eval_run_id),
                        },
                    },
                )
                return None if row is None else EvalRunItem.model_validate(dict(row))
            except Exception as exc:
                span.record_exception(exc)
                EVAL_SERVICE_CALLS_TOTAL.labels(
                    method="get_run_status", outcome="error"
                ).inc()
                LOGGER.error(
                    "eval run status lookup failed",
                    extra={
                        "event": "eval_run_status_lookup_failed",
                        "context": {"tenant_id_hash": tenant_hash},
                    },
                    exc_info=True,
                )
                raise
            finally:
                EVAL_SERVICE_DURATION_SECONDS.labels(method="get_run_status").observe(
                    perf_counter() - started_at
                )

    async def _run_eval_background(
        self,
        *,
        tenant_id: UUID,
        eval_run_id: UUID,
    ) -> None:
        tenant_hash = _sha256_short(str(tenant_id))
        try:
            async with self._db_session_factory() as session:
                await self._eval_runner(
                    cases_path=self._cases_path,
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
                    "context": {
                        "tenant_id_hash": tenant_hash,
                        "eval_run_id": str(eval_run_id),
                    },
                },
                exc_info=True,
            )
            async with self._db_session_factory() as session:
                await self._mark_run_status(
                    session=session,
                    tenant_id=tenant_id,
                    eval_run_id=eval_run_id,
                    status="failed",
                    completed_at=datetime.now(UTC),
                )

    async def _mark_run_status(
        self,
        *,
        session,
        tenant_id: UUID,
        eval_run_id: UUID,
        status: str,
        completed_at: datetime | None = None,
    ) -> None:
        async with session.begin():
            await session.execute(
                text("SET LOCAL app.current_tenant_id = :tid"),
                {"tid": str(tenant_id)},
            )
            if completed_at is None:
                await session.execute(
                    text(
                        """
                        UPDATE eval_runs
                        SET status = :status
                        WHERE eval_run_id = :eval_run_id AND tenant_id = :tenant_id
                        """
                    ),
                    {
                        "status": status,
                        "eval_run_id": str(eval_run_id),
                        "tenant_id": str(tenant_id),
                    },
                )
                return
            await session.execute(
                text(
                    """
                    UPDATE eval_runs
                    SET status = :status, completed_at = :completed_at
                    WHERE eval_run_id = :eval_run_id AND tenant_id = :tenant_id
                    """
                ),
                {
                    "status": status,
                    "completed_at": completed_at,
                    "eval_run_id": str(eval_run_id),
                    "tenant_id": str(tenant_id),
                },
            )

    def _parse_cursor(self, cursor: str | None) -> datetime | None:
        if cursor is None:
            return None
        try:
            return datetime.fromisoformat(cursor)
        except ValueError as exc:
            raise InvalidCursorError("cursor must be a valid ISO timestamp") from exc
