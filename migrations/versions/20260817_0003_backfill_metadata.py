"""Create operational DailyBar backfill attempt ledger."""

import sqlalchemy as sa
from alembic import op

revision = "20260817_0003"
down_revision = "20260814_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_bar_backfill_attempts",
        sa.Column("attempt_id", sa.String(80), primary_key=True),
        sa.Column("provider_id", sa.String(255), nullable=False),
        sa.Column("capability", sa.String(255), nullable=False),
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("instrument_type", sa.String(32), nullable=False),
        sa.Column("requested_start", sa.Date(), nullable=False),
        sa.Column("requested_end", sa.Date(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("received_count", sa.BigInteger(), nullable=False),
        sa.Column("persisted_count", sa.BigInteger(), nullable=False),
        sa.Column("already_exists_count", sa.BigInteger(), nullable=False),
        sa.Column("failed_count", sa.BigInteger(), nullable=False),
        sa.Column("error_code", sa.String(128)),
        sa.CheckConstraint("requested_end >= requested_start", name="ck_backfill_date_range"),
        sa.CheckConstraint(
            "received_count >= 0 AND persisted_count >= 0 "
            "AND already_exists_count >= 0 AND failed_count >= 0",
            name="ck_backfill_counts_nonnegative",
        ),
    )
    op.create_index(
        "ix_backfill_instrument_range",
        "daily_bar_backfill_attempts",
        ["market", "symbol", "instrument_type", "requested_start", "requested_end"],
    )


def downgrade() -> None:
    op.drop_index("ix_backfill_instrument_range", table_name="daily_bar_backfill_attempts")
    op.drop_table("daily_bar_backfill_attempts")
