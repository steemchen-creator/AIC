"""Add immutable market evidence foundations for SPEC-011 Checkpoint A.

Revision ID: 20260921_0016
Revises: 20260910_0015
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260921_0016"
down_revision: str | None = "20260910_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _lineage_columns(*, include_times: bool = True) -> list[sa.Column[object]]:
    columns: list[sa.Column[object]] = [
        sa.Column("adapter_id", sa.String(64), nullable=False),
        sa.Column("upstream_source_id", sa.String(96), nullable=False),
        sa.Column("authority_level", sa.String(32), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
    ]
    if include_times:
        columns.extend(
            [
                sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
                sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
                sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
            ]
        )
    columns.extend(
        [
            sa.Column("published_at", sa.DateTime(timezone=True)),
            sa.Column("raw_hash", sa.String(64), nullable=False),
            sa.Column("transformation_version", sa.String(96), nullable=False),
            sa.Column("source_uri", sa.String(2048)),
            sa.Column("source_record_id", sa.String(255)),
            sa.Column("license_id", sa.String(96)),
        ]
    )
    return columns


def upgrade() -> None:
    op.create_table(
        "raw_observations",
        sa.Column("observation_id", sa.String(96), primary_key=True),
        sa.Column("provider_id", sa.String(64), nullable=False),
        sa.Column("capability", sa.String(64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_kind", sa.String(16), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("source_metadata", sa.Text(), nullable=False),
        *_lineage_columns(),
    )
    op.create_index(
        "ix_raw_observations_upstream_event",
        "raw_observations",
        ["upstream_source_id", "event_time"],
    )
    op.create_table(
        "canonical_market_quotes",
        sa.Column("quote_id", sa.String(96), primary_key=True),
        sa.Column("observation_id", sa.String(96), nullable=False),
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("instrument_type", sa.String(32), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last", sa.Numeric(28, 10), nullable=False),
        sa.Column("bid", sa.Numeric(28, 10)),
        sa.Column("ask", sa.Numeric(28, 10)),
        sa.Column("previous_close", sa.Numeric(28, 10)),
        sa.Column("volume", sa.BigInteger()),
        sa.Column("turnover", sa.Numeric(38, 10)),
        sa.Column("session_status", sa.String(24), nullable=False),
        *_lineage_columns(include_times=False),
        sa.Column("quality_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("freshness_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("completeness_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("consistency_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("source_confidence_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("quality_flags", sa.ARRAY(sa.String(64)), nullable=False),
        sa.ForeignKeyConstraint(["observation_id"], ["raw_observations.observation_id"]),
    )
    op.create_index(
        "ix_market_quotes_identity_event",
        "canonical_market_quotes",
        ["market", "symbol", "instrument_type", "event_time"],
    )
    op.create_table(
        "quote_reconciliations",
        sa.Column("reconciliation_id", sa.String(96), primary_key=True),
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("instrument_type", sa.String(32), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("contributing_quote_ids", sa.ARRAY(sa.String(96)), nullable=False),
        sa.Column("contributing_upstream_ids", sa.ARRAY(sa.String(96)), nullable=False),
        sa.Column("chosen_quote_id", sa.String(96)),
        sa.Column("confidence", sa.Numeric(8, 6), nullable=False),
        sa.Column("reasons", sa.ARRAY(sa.String(96)), nullable=False),
        sa.Column("policy_version", sa.String(96), nullable=False),
    )
    op.create_table(
        "market_pulse_observations",
        sa.Column("observation_id", sa.String(96), primary_key=True),
        sa.Column("series_id", sa.String(96), nullable=False),
        sa.Column("family", sa.String(32), nullable=False),
        sa.Column("benchmark_owner", sa.String(96), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("geography", sa.String(96), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("publication_mode", sa.String(32), nullable=False),
        sa.Column("currency", sa.String(16)),
        sa.Column("tenor_or_contract", sa.String(96)),
        sa.Column("value", sa.Numeric(38, 12), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        *_lineage_columns(include_times=False),
    )
    op.create_index(
        "ix_market_pulse_series_event",
        "market_pulse_observations",
        ["series_id", "event_time"],
    )


def downgrade() -> None:
    op.drop_table("market_pulse_observations")
    op.drop_table("quote_reconciliations")
    op.drop_table("canonical_market_quotes")
    op.drop_table("raw_observations")
