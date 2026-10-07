"""all listed companies and congress trades

Splits trades into a shared table plus insider and Congress detail tables,
widens companies from the S&P 500 to every Nasdaq/NYSE/Cboe listing, and
records committee leadership.

Trades and alerts are rebuilt rather than converted: nothing had been
deployed when this was written, and Form 4 history can be re-fetched from
SEC with `python -m app.cli nightly --no-alerts`.

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

EMPTY_LIST = sa.text("'[]'")


def upgrade() -> None:
    op.drop_table("alerts")
    op.drop_table("trades")
    op.drop_table("ingested_days")

    with op.batch_alter_table("users") as batch:
        batch.drop_column("include_unverified")

    with op.batch_alter_table("companies") as batch:
        batch.alter_column("sub_industry", new_column_name="industry", existing_type=sa.String(128))
        batch.add_column(sa.Column("other_tickers", sa.JSON(), nullable=False, server_default=EMPTY_LIST))
        batch.add_column(sa.Column("exchange", sa.String(16), nullable=False, server_default=""))
        batch.add_column(sa.Column("sic_code", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("industry_checked_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("listed", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.create_index("ix_companies_listed", ["listed"])

    with op.batch_alter_table("politicians") as batch:
        batch.add_column(sa.Column("led_committees", sa.JSON(), nullable=False, server_default=EMPTY_LIST))

    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("external_id", sa.String(64), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="SET NULL"), nullable=True),
        sa.Column("politician_id", sa.Integer(), sa.ForeignKey("politicians.id", ondelete="SET NULL"), nullable=True),
        sa.Column("ticker", sa.String(16), nullable=False),
        sa.Column("asset_name", sa.String(256), nullable=False),
        sa.Column("actor_name", sa.String(256), nullable=False),
        sa.Column("actor_role", sa.String(256), nullable=False),
        sa.Column("direction", sa.String(4), nullable=False),
        sa.Column("value_low", sa.Float(), nullable=True),
        sa.Column("value_high", sa.Float(), nullable=True),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("filed_date", sa.Date(), nullable=False),
        sa.Column("source_url", sa.String(512), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("review_reason", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source", "external_id", name="uq_trades_source_external_id"),
    )
    for column in ("company_id", "politician_id", "ticker", "trade_date", "filed_date", "score", "needs_review"):
        op.create_index(f"ix_trades_{column}", "trades", [column])

    op.create_table(
        "insider_trade_details",
        sa.Column("trade_id", sa.Integer(), sa.ForeignKey("trades.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("accession_no", sa.String(25), nullable=False),
        sa.Column("transaction_code", sa.String(1), nullable=False),
        sa.Column("shares", sa.Float(), nullable=False),
        sa.Column("avg_price", sa.Float(), nullable=True),
        sa.Column("shares_owned_after", sa.Float(), nullable=True),
        sa.Column("is_10b5_1", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_insider_trade_details_accession_no", "insider_trade_details", ["accession_no"])

    op.create_table(
        "congress_trade_details",
        sa.Column("trade_id", sa.Integer(), sa.ForeignKey("trades.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("chamber", sa.String(8), nullable=False),
        sa.Column("owner", sa.String(32), nullable=False),
        sa.Column("amount_range", sa.String(64), nullable=False),
        sa.Column("transaction_type", sa.String(32), nullable=False),
        sa.Column("description", sa.String(512), nullable=False),
    )

    op.create_table(
        "processed_filings",
        sa.Column("accession_no", sa.String(25), primary_key=True),
        sa.Column("filed_date", sa.Date(), nullable=False),
        sa.Column("trades", sa.Integer(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_processed_filings_filed_date", "processed_filings", ["filed_date"])

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trade_id", sa.Integer(), sa.ForeignKey("trades.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "trade_id", name="uq_alerts_user_trade"),
    )
    for column in ("user_id", "trade_id", "status"):
        op.create_index(f"ix_alerts_{column}", "alerts", [column])


def downgrade() -> None:
    raise NotImplementedError("0003 rebuilds the trade tables; restore from a backup taken before upgrading.")
