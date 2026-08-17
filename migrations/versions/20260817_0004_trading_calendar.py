"""Create canonical trading-calendar facts and coverage ledger."""

import sqlalchemy as sa
from alembic import op

revision = "20260817_0004"
down_revision = "20260817_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trading_calendar_days",
        sa.Column("market", sa.String(32), primary_key=True),
        sa.Column("trading_date", sa.Date(), primary_key=True),
        sa.Column("is_open", sa.Boolean(), nullable=False),
        sa.Column("morning_open", sa.DateTime(timezone=True)),
        sa.Column("break_start", sa.DateTime(timezone=True)),
        sa.Column("break_end", sa.DateTime(timezone=True)),
        sa.Column("session_close", sa.DateTime(timezone=True)),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_id", sa.String(255), nullable=False),
        sa.Column("source_record_id", sa.String(255)),
        sa.Column("source_uri", sa.String(2048)),
        sa.Column("raw_payload_hash", sa.String(64), nullable=False),
        sa.Column("transformation_version", sa.String(255), nullable=False),
    )
    op.create_index("ix_calendar_market_date", "trading_calendar_days", ["market", "trading_date"])
    op.create_table(
        "calendar_backfill_attempts",
        sa.Column("attempt_id", sa.String(80), primary_key=True),
        sa.Column("provider_id", sa.String(255), nullable=False),
        sa.Column("market", sa.String(32), nullable=False),
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
    )
    op.create_index(
        "ix_calendar_backfill_range",
        "calendar_backfill_attempts",
        ["market", "requested_start", "requested_end"],
    )


def downgrade() -> None:
    op.drop_index("ix_calendar_backfill_range", table_name="calendar_backfill_attempts")
    op.drop_table("calendar_backfill_attempts")
    op.drop_index("ix_calendar_market_date", table_name="trading_calendar_days")
    op.drop_table("trading_calendar_days")
