"""Enquiries store a first and last name, and a WhatsApp number

The single `name` column was read back with `.split()[0]` to find a first name
for the acknowledgement email, which calls "Mary Jane Smith" Mary. `User` was
split for the same reason on 2026-09-01; this brings enquiries into line.

The backfill splits on the *first* space, so "Mary Jane Smith" becomes
"Mary" + "Jane Smith". That is a guess, and it is the last time one is made —
every enquiry from here holds what the person actually typed into two fields.
A name with no space at all keeps the whole thing as the first name and leaves
the surname empty, rather than inventing one.

Revision ID: a1c4e70b93d2
Revises: 06b041c54bc7
"""

from alembic import op
import sqlalchemy as sa

revision = "a1c4e70b93d2"
down_revision = "06b041c54bc7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Added nullable, backfilled, then made NOT NULL: SQLite cannot add a
    # NOT NULL column to a table that already has rows, and production has
    # real enquiries in it.
    with op.batch_alter_table("enquiries") as batch:
        batch.add_column(sa.Column("first_name", sa.String(120), nullable=True))
        batch.add_column(sa.Column("last_name", sa.String(120), nullable=True))
        batch.add_column(sa.Column("whatsapp", sa.String(50), nullable=True))

    enquiries = sa.table(
        "enquiries",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("first_name", sa.String),
        sa.column("last_name", sa.String),
    )

    # In Python rather than SQL: splitting on the first space differs between
    # Postgres and SQLite, and this runs against both.
    connection = op.get_bind()
    for row in connection.execute(sa.select(enquiries.c.id, enquiries.c.name)):
        whole = (row.name or "").strip()
        first, _, last = whole.partition(" ")
        connection.execute(
            enquiries.update()
            .where(enquiries.c.id == row.id)
            .values(first_name=first or "Unknown", last_name=last.strip())
        )

    with op.batch_alter_table("enquiries") as batch:
        batch.alter_column("first_name", existing_type=sa.String(120), nullable=False)
        batch.alter_column("last_name", existing_type=sa.String(120), nullable=False)
        batch.drop_column("name")


def downgrade() -> None:
    with op.batch_alter_table("enquiries") as batch:
        batch.add_column(sa.Column("name", sa.String(255), nullable=True))

    enquiries = sa.table(
        "enquiries",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("first_name", sa.String),
        sa.column("last_name", sa.String),
    )
    connection = op.get_bind()
    for row in connection.execute(
        sa.select(enquiries.c.id, enquiries.c.first_name, enquiries.c.last_name)
    ):
        connection.execute(
            enquiries.update()
            .where(enquiries.c.id == row.id)
            .values(name=f"{row.first_name} {row.last_name}".strip())
        )

    with op.batch_alter_table("enquiries") as batch:
        batch.alter_column("name", existing_type=sa.String(255), nullable=False)
        batch.drop_column("whatsapp")
        batch.drop_column("last_name")
        batch.drop_column("first_name")
