"""pro alert options

Adds the Pro flag and two Pro alert options to users (skip pre-planned sales, notable feed), and records why
each alert was sent (a starred company or politician, or the notable feed).

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("is_pro", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("skip_planned_sales", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("notable_feed", sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table("alerts") as batch:
        batch.add_column(sa.Column("reason", sa.String(16), nullable=False, server_default="starred"))


def downgrade() -> None:
    with op.batch_alter_table("alerts") as batch:
        batch.drop_column("reason")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("notable_feed")
        batch.drop_column("skip_planned_sales")
        batch.drop_column("is_pro")
