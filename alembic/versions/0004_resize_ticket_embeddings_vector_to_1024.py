"""Resize ticket_embeddings vector dimension to 1024 when pgvector is active."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_vector_column() -> bool:
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            """
            SELECT udt_name
            FROM information_schema.columns
            WHERE table_name = 'ticket_embeddings' AND column_name = 'embedding'
            LIMIT 1
            """
        )
    ).first()
    if row is None:
        return False
    return str(row[0]) == "vector"


def upgrade() -> None:
    if _is_vector_column():
        op.execute(
            sa.text(
                "ALTER TABLE ticket_embeddings ALTER COLUMN embedding TYPE VECTOR(1024)"
            )
        )


def downgrade() -> None:
    if _is_vector_column():
        op.execute(
            sa.text(
                "ALTER TABLE ticket_embeddings ALTER COLUMN embedding TYPE VECTOR(1536)"
            )
        )
