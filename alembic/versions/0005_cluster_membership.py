"""Persist RCA cluster membership rows."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rca_cluster_members",
        sa.Column(
            "cluster_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cluster_summaries.cluster_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ticket_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tickets.ticket_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint(
            "cluster_id", "ticket_id", name="pk_rca_cluster_members"
        ),
    )
    op.create_index(
        "ix_rca_cluster_members_cluster_id",
        "rca_cluster_members",
        ["cluster_id"],
    )
    op.execute("ALTER TABLE rca_cluster_members ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON rca_cluster_members
        USING (
            EXISTS (
                SELECT 1
                FROM cluster_summaries
                WHERE cluster_summaries.cluster_id = rca_cluster_members.cluster_id
                  AND cluster_summaries.tenant_id =
                    current_setting('app.current_tenant_id', TRUE)::UUID
            )
        )
        """
    )
    op.execute("GRANT ALL ON TABLE rca_cluster_members TO gdev_admin")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE rca_cluster_members TO gdev_app"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON rca_cluster_members")
    op.drop_index("ix_rca_cluster_members_cluster_id", table_name="rca_cluster_members")
    op.drop_table("rca_cluster_members")
