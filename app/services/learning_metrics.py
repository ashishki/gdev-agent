"""Tenant learning/adoption metrics derived from approval events."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas import LearningMetricsResponse

UTC = timezone.utc
DEFAULT_LEARNING_WINDOW_DAYS = 7
DEFAULT_MIN_SAMPLE_SIZE = 20


async def fetch_learning_metrics(
    *,
    db: AsyncSession,
    tenant_id: UUID,
    window_days: int = DEFAULT_LEARNING_WINDOW_DAYS,
    min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
) -> LearningMetricsResponse:
    """Return tenant approval latency and override/rejection rates for a recent window."""
    window_start = datetime.now(UTC) - timedelta(days=window_days)
    row = (
        (
            await db.execute(
                text(
                    """
                    WITH scoped_events AS (
                        SELECT decision, latency_ms, override_kind
                        FROM approval_events
                        WHERE tenant_id = :tenant_id
                          AND created_at >= :window_start
                    )
                    SELECT
                        COUNT(*)::integer AS reviewed_count,
                        (
                            SELECT
                                ROUND(
                                    (
                                        percentile_cont(0.5)
                                        WITHIN GROUP (ORDER BY latency_ms)
                                    )::numeric
                                )::integer
                            FROM scoped_events
                            WHERE latency_ms IS NOT NULL
                        ) AS approval_latency_p50_ms,
                        (
                            SELECT
                                ROUND(
                                    (
                                        percentile_cont(0.95)
                                        WITHIN GROUP (ORDER BY latency_ms)
                                    )::numeric
                                )::integer
                            FROM scoped_events
                            WHERE latency_ms IS NOT NULL
                        ) AS approval_latency_p95_ms,
                        COALESCE(
                            ROUND(
                                (
                                    COUNT(*) FILTER (WHERE decision = 'approved')
                                )::numeric / NULLIF(COUNT(*), 0),
                                3
                            ),
                            0
                        ) AS approval_rate,
                        COALESCE(
                            ROUND(
                                (
                                    COUNT(*) FILTER (WHERE decision = 'rejected')
                                )::numeric / NULLIF(COUNT(*), 0),
                                3
                            ),
                            0
                        ) AS rejection_rate,
                        COALESCE(
                            ROUND(
                                (
                                    COUNT(*) FILTER (WHERE override_kind IS NOT NULL)
                                )::numeric / NULLIF(COUNT(*), 0),
                                3
                            ),
                            0
                        ) AS override_rate
                    FROM scoped_events
                    """
                ),
                {
                    "tenant_id": str(tenant_id),
                    "window_start": window_start,
                },
            )
        )
        .mappings()
        .first()
    )
    reviewed_count = int(row["reviewed_count"] or 0) if row else 0

    return LearningMetricsResponse(
        window_days=window_days,
        min_sample_size=min_sample_size,
        reviewed_count=reviewed_count,
        approval_latency_p50_ms=_optional_int(row, "approval_latency_p50_ms"),
        approval_latency_p95_ms=_optional_int(row, "approval_latency_p95_ms"),
        approval_rate=_decimal_value(row, "approval_rate"),
        rejection_rate=_decimal_value(row, "rejection_rate"),
        override_rate=_decimal_value(row, "override_rate"),
        sample_size_warning=reviewed_count < min_sample_size,
    )


def _optional_int(row, key: str) -> int | None:  # noqa: ANN001
    if row is None or row[key] is None:
        return None
    return int(row[key])


def _decimal_value(row, key: str) -> Decimal:  # noqa: ANN001
    if row is None or row[key] is None:
        return Decimal("0")
    return Decimal(str(row[key]))
