"""planned_run.replacement_reason: record why a plan was replaced

Additive and nullable: existing rows are untouched. SQLite performs this as a
native ADD COLUMN (no table rebuild). "REPLACED requires a reason" is enforced
in the service layer; a CHECK constraint would force a rebuild of planned_run,
which other tables reference.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-15 20:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("planned_run", schema=None) as batch_op:
        batch_op.add_column(sa.Column("replacement_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("planned_run", schema=None) as batch_op:
        batch_op.drop_column("replacement_reason")
