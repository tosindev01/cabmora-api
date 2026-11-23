"""Watermarks come off on payment, and sharing is the admin's call

The watermark used to lift on the client's approval, which handed over the
finished files before any money had arrived — they approved the work and
already had everything they were paying for. It now lifts when the project is
settled, so the enum value is renamed rather than reinterpreted: leaving it
called `until_approved` while it meant something else would mislead everyone
who read it afterwards.

`allow_client_sharing` arrives off for every existing project. A public link
that needs no account is a decision about photographs of people who agreed to
none of this, and inheriting it on a few hundred historic projects is not a
decision anybody made.

Revision ID: e5b73c02a918
Revises: d4a92c1e8b73
"""

from alembic import op
import sqlalchemy as sa

revision = "e5b73c02a918"
down_revision = "d4a92c1e8b73"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(
            sa.Column(
                "allow_client_sharing",
                sa.Boolean(),
                nullable=False,
                # SQLite cannot add a NOT NULL column without one, and every
                # existing row must land on the safe side of this anyway.
                server_default=sa.false(),
            )
        )

    op.execute(
        "UPDATE projects SET watermark_policy = 'until_paid' "
        "WHERE watermark_policy = 'until_approved'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE projects SET watermark_policy = 'until_approved' "
        "WHERE watermark_policy = 'until_paid'"
    )
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("allow_client_sharing")
