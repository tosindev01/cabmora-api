"""Sections a coordinator has been let into, on top of their role

A table rather than a column so "who can see payments?" is a query, and so a
grant can carry who gave it and when — the question asked after something goes
wrong, and the one a JSON blob cannot answer.

Empty for everybody on arrival. Nobody gains access from this migration.

Revision ID: c8e52a90f417
Revises: b9d41f72c3ae
"""

from alembic import op
import sqlalchemy as sa

revision = "c8e52a90f417"
down_revision = "b9d41f72c3ae"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_permissions",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("permission", sa.String(40), primary_key=True),
        sa.Column("granted_by", sa.String(36), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_user_permissions_user_id", "user_permissions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_permissions_user_id", table_name="user_permissions")
    op.drop_table("user_permissions")
