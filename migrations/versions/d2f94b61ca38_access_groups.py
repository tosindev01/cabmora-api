"""Named bundles of permissions, assignable to people

An additive role in everything but name: a group only ever adds to what the
base role gives, and is bounded by the same grantable list as a direct grant —
otherwise a group containing USERS would be a ladder out of the whole
mechanism.

No groups exist on arrival and nobody is in one, so nothing changes for
anybody until an administrator makes one.

Revision ID: d2f94b61ca38
Revises: c8e52a90f417
"""

from alembic import op
import sqlalchemy as sa

revision = "d2f94b61ca38"
down_revision = "c8e52a90f417"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "access_groups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(60), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "access_group_permissions",
        sa.Column("group_id", sa.String(36), primary_key=True),
        sa.Column("permission", sa.String(40), primary_key=True),
    )
    op.create_index(
        "ix_access_group_permissions_group_id",
        "access_group_permissions",
        ["group_id"],
    )
    op.create_table(
        "user_groups",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("group_id", sa.String(36), primary_key=True),
    )
    op.create_index("ix_user_groups_user_id", "user_groups", ["user_id"])
    op.create_index("ix_user_groups_group_id", "user_groups", ["group_id"])


def downgrade() -> None:
    op.drop_index("ix_user_groups_group_id", table_name="user_groups")
    op.drop_index("ix_user_groups_user_id", table_name="user_groups")
    op.drop_table("user_groups")
    op.drop_index(
        "ix_access_group_permissions_group_id", table_name="access_group_permissions"
    )
    op.drop_table("access_group_permissions")
    op.drop_table("access_groups")
