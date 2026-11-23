"""Contact details on the user, price and payment method on the project

Phone and WhatsApp were collected on the enquiry and stranded there: the
moment a lead became a project its client had no reachable number anywhere.
They belong to the person, who may never have filled in an enquiry at all.

The price is what the job costs, in minor units like every other money here.
The payment method is intent — how this client is expected to pay — and is
distinct from `Payment.method`, which records how a sum actually arrived.

Revision ID: d4a92c1e8b73
Revises: c3e81b7fa204
"""

from alembic import op
import sqlalchemy as sa

revision = "d4a92c1e8b73"
down_revision = "c3e81b7fa204"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("phone", sa.String(50), nullable=True))
        batch.add_column(sa.Column("whatsapp", sa.String(50), nullable=True))

    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("price_minor", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("payment_method", sa.String(20), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("payment_method")
        batch.drop_column("price_minor")

    with op.batch_alter_table("users") as batch:
        batch.drop_column("whatsapp")
        batch.drop_column("phone")
