"""Add domestic ETF, index reference, valuation, and execution profiles.

Revision ID: 20260906_0013
Revises: 20260906_0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260906_0013"
down_revision: str | None = "20260906_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "etf_instrument_profiles",
        sa.Column("instrument_key", sa.String(128), primary_key=True),
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("expanded_name", sa.String(255)),
        sa.Column("listing_date", sa.Date()),
        sa.Column("delisting_date", sa.Date()),
        sa.Column("listing_status", sa.String(32), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("benchmark_symbol", sa.String(128)),
        sa.Column("fund_manager", sa.String(255)),
        sa.Column("management_fee", sa.Numeric(28, 10)),
        sa.Column("underlying_market", sa.String(32), nullable=False),
        sa.Column("underlying_currency", sa.String(16), nullable=False),
        sa.Column("trading_currency", sa.String(16), nullable=False),
        sa.Column("exposure_category", sa.String(64), nullable=False),
        sa.Column("exposure_family", sa.String(64), nullable=False),
        sa.Column("provenance", postgresql.JSONB(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_etf_profiles_listing", "etf_instrument_profiles", ["market", "listing_status"]
    )
    op.create_table(
        "index_references",
        sa.Column("index_key", sa.String(128), primary_key=True),
        sa.Column("symbol", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("publisher", sa.String(255)),
        sa.Column("base_date", sa.Date()),
        sa.Column("base_value", sa.Numeric(28, 10)),
        sa.Column("exposure_market", sa.String(32), nullable=False),
        sa.Column("point_currency", sa.String(16), nullable=False),
        sa.Column("provenance", postgresql.JSONB(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "etf_index_relationships",
        sa.Column("relationship_id", sa.String(300), primary_key=True),
        sa.Column("etf_market", sa.String(32), nullable=False),
        sa.Column("etf_symbol", sa.String(64), nullable=False),
        sa.Column("benchmark_symbol", sa.String(128), nullable=False),
        sa.Column("effective_from", sa.Date()),
        sa.Column("effective_to", sa.Date()),
        sa.Column("current_relationship_only", sa.Boolean(), nullable=False),
        sa.Column("provenance", postgresql.JSONB(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_etf_relationships_instrument",
        "etf_index_relationships",
        ["etf_market", "etf_symbol", "available_at"],
    )
    op.create_table(
        "etf_valuation_snapshots",
        sa.Column("valuation_id", sa.String(200), primary_key=True),
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("nav", sa.Numeric(28, 10)),
        sa.Column("close_price", sa.Numeric(28, 10)),
        sa.Column("share_size", sa.Numeric(38, 10)),
        sa.Column("premium_discount_pct", sa.Numeric(28, 10)),
        sa.Column("provenance", postgresql.JSONB(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_etf_valuations_instrument_date",
        "etf_valuation_snapshots",
        ["market", "symbol", "trading_date", "available_at"],
    )
    op.create_table(
        "instrument_execution_profiles",
        sa.Column("profile_id", sa.String(200), primary_key=True),
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("instrument_type", sa.String(32), nullable=False),
        sa.Column("trading_currency", sa.String(16), nullable=False),
        sa.Column("board_lot", sa.Integer(), nullable=False),
        sa.Column("settlement_capability", sa.String(16), nullable=False),
        sa.Column("price_limit_policy_reference", sa.String(255), nullable=False),
        sa.Column("calendar_reference", sa.String(32), nullable=False),
        sa.Column("source", sa.String(512), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("policy_version", sa.String(128), nullable=False),
    )
    op.create_index(
        "ix_execution_profiles_instrument",
        "instrument_execution_profiles",
        ["market", "symbol", "instrument_type", "effective_from", "available_at"],
    )


def downgrade() -> None:
    for index_name, table_name in (
        ("ix_execution_profiles_instrument", "instrument_execution_profiles"),
        ("ix_etf_valuations_instrument_date", "etf_valuation_snapshots"),
        ("ix_etf_relationships_instrument", "etf_index_relationships"),
        ("ix_etf_profiles_listing", "etf_instrument_profiles"),
    ):
        op.drop_index(index_name, table_name=table_name)
        op.drop_table(table_name)
    op.drop_table("index_references")
