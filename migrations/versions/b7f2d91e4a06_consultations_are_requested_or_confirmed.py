"""Consultations are requested or confirmed

A client picking a slot on the website is asking, not booking. The calendar
only knows about calls made through this platform, so a slot that looks free
may not be — confirming is what creates the calendar entry and the link.

Existing rows become CONFIRMED: every consultation before this was created by
an admin, and creating one was agreeing to it.

Revision ID: b7f2d91e4a06
Revises: a1c4e70b93d2
"""

from alembic import op
import sqlalchemy as sa

revision = "b7f2d91e4a06"
down_revision = "a1c4e70b93d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("consultations") as batch:
        batch.add_column(
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                # Both a backfill for existing rows and the column default, so
                # an admin booking a call still gets a confirmed one.
                server_default="confirmed",
            )
        )
        batch.create_index("ix_consultations_status", ["status"])


def downgrade() -> None:
    with op.batch_alter_table("consultations") as batch:
        batch.drop_index("ix_consultations_status")
        batch.drop_column("status")
