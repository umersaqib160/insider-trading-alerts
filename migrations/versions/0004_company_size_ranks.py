"""company size ranks

Adds each company's size rank (order of SEC's ticker file, which follows market value) and its rank
among S&P 500 members, used by the notable score. Both are filled by the next load-refdata / nightly run.

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("companies") as batch:
        batch.add_column(sa.Column("size_rank", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("sp500_rank", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("companies") as batch:
        batch.drop_column("sp500_rank")
        batch.drop_column("size_rank")
