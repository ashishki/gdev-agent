"""Add approval learning metrics fields."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pending_decisions",
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column("approval_events", sa.Column("latency_ms", sa.Integer(), nullable=True))
    op.add_column("approval_events", sa.Column("override_kind", sa.Text(), nullable=True))
    op.add_column("approval_events", sa.Column("override_reason", sa.Text(), nullable=True))
    op.add_column("eval_runs", sa.Column("reviewed_count", sa.Integer(), nullable=True))
    op.add_column("eval_runs", sa.Column("approval_latency_p50_ms", sa.Integer(), nullable=True))
    op.add_column("eval_runs", sa.Column("approval_latency_p95_ms", sa.Integer(), nullable=True))
    op.add_column("eval_runs", sa.Column("override_rate", sa.Numeric(4, 3), nullable=True))
    op.add_column("eval_runs", sa.Column("rejection_rate", sa.Numeric(4, 3), nullable=True))
    op.add_column(
        "eval_runs",
        sa.Column(
            "learning_sample_size_warning",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )


def downgrade() -> None:
    op.drop_column("eval_runs", "learning_sample_size_warning")
    op.drop_column("eval_runs", "rejection_rate")
    op.drop_column("eval_runs", "override_rate")
    op.drop_column("eval_runs", "approval_latency_p95_ms")
    op.drop_column("eval_runs", "approval_latency_p50_ms")
    op.drop_column("eval_runs", "reviewed_count")
    op.drop_column("approval_events", "override_reason")
    op.drop_column("approval_events", "override_kind")
    op.drop_column("approval_events", "latency_ms")
    op.drop_column("pending_decisions", "resolved_at")
