"""What the client thought of the work

One row per project, enforced by a unique index rather than by everybody
remembering to look first.

Revision ID: a7c35e91d208
Revises: f1a28d6c4b57
"""

from alembic import op
import sqlalchemy as sa

revision = "a7c35e91d208"
down_revision = "f1a28d6c4b57"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ratings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("customer_id", sa.String(36), nullable=False, index=True),
        sa.Column("stars", sa.Integer(), nullable=False),
        sa.Column("words", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ratings_project_id", "ratings", ["project_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_ratings_project_id", table_name="ratings")
    op.drop_table("ratings")
