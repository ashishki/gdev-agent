"""Grant BYPASSRLS to gdev_admin role."""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER ROLE gdev_admin BYPASSRLS")


def downgrade() -> None:
    op.execute("ALTER ROLE gdev_admin NOBYPASSRLS")
