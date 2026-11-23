"""Moderation and consent on a client's rating

`may_publish` arrives false for every existing row, which is the only
defensible default: a rating left in a private portal was never an offer to
appear on a website, and backfilling consent nobody gave would be worse than
having no reviews at all.

Revision ID: b9d41f72c3ae
Revises: a7c35e91d208
"""

from alembic import op
import sqlalchemy as sa

revision = "b9d41f72c3ae"
down_revision = "a7c35e91d208"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ratings") as batch:
        batch.add_column(
            sa.Column(
                "may_publish", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
        batch.add_column(
            sa.Column(
                "status", sa.String(20), nullable=False, server_default="pending"
            )
        )
        batch.add_column(sa.Column("moderated_by", sa.String(36), nullable=True))
        batch.add_column(
            sa.Column("moderated_at", sa.DateTime(timezone=True), nullable=True)
        )
    op.create_index("ix_ratings_status", "ratings", ["status"])


def downgrade() -> None:
    op.drop_index("ix_ratings_status", table_name="ratings")
    with op.batch_alter_table("ratings") as batch:
        batch.drop_column("moderated_at")
        batch.drop_column("moderated_by")
        batch.drop_column("status")
        batch.drop_column("may_publish")
