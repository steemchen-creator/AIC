"""Create instrument master, daily trading status, and operational coverage."""

import sqlalchemy as sa
from alembic import op

revision = "20260817_0005"
down_revision = "20260817_0004"
branch_labels = None
depends_on = None


def _provenance() -> list[sa.Column]:
    return [
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_id", sa.String(255), nullable=False),
        sa.Column("source_record_id", sa.String(255)),
        sa.Column("source_uri", sa.String(2048)),
        sa.Column("raw_payload_hash", sa.String(64), nullable=False),
        sa.Column("transformation_version", sa.String(255), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "instrument_masters",
        sa.Column("canonical_key", sa.String(96), primary_key=True),
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("instrument_type", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("listing_date", sa.Date()),
        sa.Column("delisting_date", sa.Date()),
        sa.Column("listing_status", sa.String(32), nullable=False),
        *_provenance(),
        sa.UniqueConstraint(
            "market", "symbol", "instrument_type", name="uq_instrument_market_symbol_type"
        ),
        sa.CheckConstraint(
            "delisting_date IS NULL OR listing_date IS NOT NULL",
            name="ck_instrument_delist_requires_list",
        ),
        sa.CheckConstraint(
            "delisting_date IS NULL OR delisting_date >= listing_date",
            name="ck_instrument_lifecycle",
        ),
    )
    op.create_index("ix_instrument_market_symbol", "instrument_masters", ["market", "symbol"])
    op.create_table(
        "instrument_trading_statuses",
        sa.Column("canonical_key", sa.String(96), primary_key=True),
        sa.Column("trading_date", sa.Date(), primary_key=True),
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("instrument_type", sa.String(32), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(512)),
        *_provenance(),
    )
    op.create_index(
        "ix_instrument_status_range",
        "instrument_trading_statuses",
        ["canonical_key", "trading_date"],
    )
    op.create_table(
        "instrument_sync_attempts",
        sa.Column("attempt_id", sa.String(80), primary_key=True),
        sa.Column("provider_id", sa.String(255), nullable=False),
        sa.Column("capability", sa.String(128), nullable=False),
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("canonical_key", sa.String(96)),
        sa.Column("symbol", sa.String(32)),
        sa.Column("requested_start", sa.Date()),
        sa.Column("requested_end", sa.Date()),
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
        "ix_instrument_sync_lookup",
        "instrument_sync_attempts",
        ["capability", "canonical_key", "requested_start", "requested_end"],
    )


def downgrade() -> None:
    op.drop_index("ix_instrument_sync_lookup", table_name="instrument_sync_attempts")
    op.drop_table("instrument_sync_attempts")
    op.drop_index("ix_instrument_status_range", table_name="instrument_trading_statuses")
    op.drop_table("instrument_trading_statuses")
    op.drop_index("ix_instrument_market_symbol", table_name="instrument_masters")
    op.drop_table("instrument_masters")
