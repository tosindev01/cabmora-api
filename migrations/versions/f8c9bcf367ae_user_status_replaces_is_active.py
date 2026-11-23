"""user status replaces is_active

Revision ID: f8c9bcf367ae
Revises: 5fa233b884a7
Create Date: 2026-09-01 12:11:25.334867

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f8c9bcf367ae'
down_revision: Union[str, Sequence[str], None] = '5fa233b884a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Replace the is_active boolean with a three-state status.

    Autogenerate produced a bare add-column/drop-column, which would have made
    `status` NOT NULL with nothing in it and thrown away every account's
    active/suspended state. The column is therefore added nullable, backfilled
    from the boolean, and only then tightened.

    An existing `is_active = true` becomes ACTIVE rather than PENDING: these
    accounts pre-date acceptance and were already using the platform, so
    putting them in a queue would lock out real users at deploy time.
    """
    op.add_column("users", sa.Column("status", sa.String(length=20), nullable=True))
    op.execute(
        "UPDATE users SET status = CASE WHEN is_active THEN 'active' ELSE 'suspended' END"
    )
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column(
            "status", existing_type=sa.String(length=20), nullable=False
        )
        batch_op.drop_column("is_active")


def downgrade() -> None:
    """PENDING has no boolean equivalent; it collapses to active on the way
    back, which is why this direction is lossy and should be a last resort."""
    op.add_column("users", sa.Column("is_active", sa.Boolean(), nullable=True))
    op.execute("UPDATE users SET is_active = (status != 'suspended')")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column("is_active", existing_type=sa.Boolean(), nullable=False)
        batch_op.drop_column("status")
