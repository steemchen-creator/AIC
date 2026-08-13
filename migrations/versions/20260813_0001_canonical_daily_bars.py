"""Create immutable canonical DailyBar storage."""

import sqlalchemy as sa
from alembic import op

revision = "20260813_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canonical_daily_bars",
        sa.Column("record_id", sa.String(64), primary_key=True),
        sa.Column("observation_id", sa.String(255), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("instrument_type", sa.String(32), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(28, 10), nullable=False),
        sa.Column("high", sa.Numeric(28, 10), nullable=False),
        sa.Column("low", sa.Numeric(28, 10), nullable=False),
        sa.Column("close", sa.Numeric(28, 10), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("turnover", sa.Numeric(38, 10), nullable=False),
        sa.Column("provider_id", sa.String(255), nullable=False),
        sa.Column("source_record_id", sa.String(255)),
        sa.Column("source_uri", sa.String(2048)),
        sa.Column("provider_timestamp", sa.DateTime(timezone=True)),
        sa.Column("received_via_failover", sa.Boolean(), nullable=False),
        sa.Column("failover_count", sa.BigInteger(), nullable=False),
        sa.Column("raw_payload_hash", sa.String(64), nullable=False),
        sa.Column("transformation_version", sa.String(255), nullable=False),
        sa.Column("quality_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("freshness_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("completeness_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("consistency_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("source_confidence_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("quality_flags", sa.ARRAY(sa.String(64)), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("canonical_daily_bars")
