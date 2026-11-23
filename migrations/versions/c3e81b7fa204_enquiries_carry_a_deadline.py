"""Enquiries carry a deadline

Agreed on the consultation call and carried to the project on conversion, so
the date everybody agreed is not re-typed — and mistyped — a week later.

Revision ID: c3e81b7fa204
Revises: b7f2d91e4a06
"""

from alembic import op
import sqlalchemy as sa

revision = "c3e81b7fa204"
down_revision = "b7f2d91e4a06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("enquiries") as batch:
        batch.add_column(sa.Column("deadline", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("enquiries") as batch:
        batch.drop_column("deadline")
