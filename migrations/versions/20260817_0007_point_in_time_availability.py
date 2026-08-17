"""Preserve point-in-time availability evidence and add PIT indexes."""

import sqlalchemy as sa
from alembic import op

revision = "20260817_0007"
down_revision = "20260817_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in (
        "trading_calendar_days",
        "instrument_masters",
        "instrument_trading_statuses",
        "adjustment_factors",
        "corporate_actions",
    ):
        op.add_column(table, sa.Column("provider_timestamp", sa.DateTime(timezone=True)))

    op.create_index(
        "ix_daily_bar_pit",
        "canonical_daily_bars",
        ["market", "symbol", "trading_date", "ingested_at", "provider_timestamp"],
    )
    op.create_index(
        "ix_calendar_pit",
        "trading_calendar_days",
        ["market", "trading_date", "retrieved_at", "provider_timestamp"],
    )
    op.create_index(
        "ix_instrument_master_pit",
        "instrument_masters",
        ["market", "listing_date", "delisting_date", "retrieved_at", "provider_timestamp"],
    )
    op.create_index(
        "ix_instrument_status_pit",
        "instrument_trading_statuses",
        ["canonical_key", "trading_date", "retrieved_at", "provider_timestamp"],
    )
    op.create_index(
        "ix_adjustment_factor_pit",
        "adjustment_factors",
        ["market", "symbol", "trading_date", "retrieved_at", "provider_timestamp"],
    )
    op.create_index(
        "ix_corporate_action_pit",
        "corporate_actions",
        ["market", "symbol", "effective_date", "retrieved_at", "provider_timestamp"],
    )


def downgrade() -> None:
    op.drop_index("ix_corporate_action_pit", table_name="corporate_actions")
    op.drop_index("ix_adjustment_factor_pit", table_name="adjustment_factors")
    op.drop_index("ix_instrument_status_pit", table_name="instrument_trading_statuses")
    op.drop_index("ix_instrument_master_pit", table_name="instrument_masters")
    op.drop_index("ix_calendar_pit", table_name="trading_calendar_days")
    op.drop_index("ix_daily_bar_pit", table_name="canonical_daily_bars")
    for table in (
        "corporate_actions",
        "adjustment_factors",
        "instrument_trading_statuses",
        "instrument_masters",
        "trading_calendar_days",
    ):
        op.drop_column(table, "provider_timestamp")
