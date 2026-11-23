"""Links that let somebody see a gallery without an account

Only the hash of the token is stored. A readable column would be a list of
working links to other people's photographs for anybody with database access,
which is the same reason a password is not kept in plaintext.

Revision ID: f1a28d6c4b57
Revises: e5b73c02a918
"""

from alembic import op
import sqlalchemy as sa

revision = "f1a28d6c4b57"
down_revision = "e5b73c02a918"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gallery_shares",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("label", sa.String(80), nullable=False, server_default=""),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("views", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Unique as well as indexed: every public request is a lookup on this
    # column, and two rows sharing a hash would be a collision in a secret.
    op.create_index(
        "ix_gallery_shares_token_hash", "gallery_shares", ["token_hash"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_gallery_shares_token_hash", table_name="gallery_shares")
    op.drop_table("gallery_shares")
