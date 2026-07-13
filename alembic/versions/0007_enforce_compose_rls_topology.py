"""Enforce non-owner application role and forced tenant RLS."""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT_SCOPED_TABLES = (
    "tenant_users",
    "api_keys",
    "webhook_secrets",
    "tickets",
    "ticket_classifications",
    "ticket_extracted_fields",
    "proposed_actions",
    "pending_decisions",
    "approval_events",
    "audit_log",
    "ticket_embeddings",
    "cluster_summaries",
    "rca_cluster_members",
    "agent_configs",
    "cost_ledger",
    "eval_runs",
)


def upgrade() -> None:
    # Existing clusters may already have a gdev_app role created by the original
    # migration. Normalize its capabilities without changing its password.
    op.execute(
        """
        ALTER ROLE gdev_app
            LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOINHERIT NOREPLICATION NOBYPASSRLS
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO gdev_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO gdev_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO gdev_app")

    for table_name in TENANT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    # Do not restore superuser/BYPASSRLS privileges during downgrade. Reversing
    # those security properties would be an unsafe and surprising side effect.
    for table_name in reversed(TENANT_SCOPED_TABLES):
        op.execute(f"ALTER TABLE IF EXISTS {table_name} NO FORCE ROW LEVEL SECURITY")
    op.execute("REVOKE USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public FROM gdev_app")
    op.execute("REVOKE USAGE ON SCHEMA public FROM gdev_app")
