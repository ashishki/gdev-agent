"""Cost ledger service for budget checks and usage accounting."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class BudgetExhaustedError(Exception):
    """Raised when tenant's daily budget has been exhausted."""

    def __init__(
        self, tenant_id: UUID, current_usd: Decimal, budget_usd: Decimal
    ) -> None:
        super().__init__(f"Daily budget exhausted for tenant {tenant_id}")
        self.tenant_id = tenant_id
        self.current_usd = current_usd
        self.budget_usd = budget_usd


class CostLedger:
    """Budget guard and token/cost accounting service."""

    async def check_budget(self, tenant_id: UUID, db: AsyncSession) -> None:
        """Raise BudgetExhaustedError if the tenant has reached today's budget."""
        result = await db.execute(
            text(
                """
                SELECT
                    t.daily_budget_usd AS budget_usd,
                    COALESCE(cl.cost_usd, 0) AS current_usd
                FROM tenants t
                LEFT JOIN cost_ledger cl
                    ON cl.tenant_id = t.tenant_id
                    AND cl.date = CURRENT_DATE
                WHERE t.tenant_id = :tenant_id
                """
            ),
            {"tenant_id": str(tenant_id)},
        )
        row = result.mappings().one_or_none()
        if row is None:
            return

        budget_usd = Decimal(str(row["budget_usd"]))
        current_usd = Decimal(str(row["current_usd"]))
        if current_usd >= budget_usd:
            raise BudgetExhaustedError(
                tenant_id=tenant_id,
                current_usd=current_usd,
                budget_usd=budget_usd,
            )

    async def record(
        self,
        tenant_id: UUID,
        day: date,
        input_tokens: int,
        output_tokens: int,
        cost_usd: Decimal,
        db: AsyncSession,
    ) -> None:
        """Atomically upsert daily token and cost usage."""
        await db.execute(
            text(
                """
                INSERT INTO cost_ledger (
                    tenant_id,
                    date,
                    input_tokens,
                    output_tokens,
                    cost_usd,
                    request_count
                )
                VALUES (
                    :tenant_id,
                    :date,
                    :input_tokens,
                    :output_tokens,
                    :cost_usd,
                    1
                )
                ON CONFLICT (tenant_id, date)
                DO UPDATE SET
                    input_tokens = cost_ledger.input_tokens + EXCLUDED.input_tokens,
                    output_tokens = cost_ledger.output_tokens + EXCLUDED.output_tokens,
                    cost_usd = cost_ledger.cost_usd + EXCLUDED.cost_usd,
                    request_count = cost_ledger.request_count + EXCLUDED.request_count
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "date": day,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost_usd,
            },
        )
