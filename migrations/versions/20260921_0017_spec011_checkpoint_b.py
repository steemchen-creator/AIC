"""Add macro, scheduled-event, and acquisition evidence for SPEC-011 Checkpoint B.

Revision ID: 20260921_0017
Revises: 20260921_0016
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260921_0017"
down_revision: str | None = "20260921_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _lineage_columns() -> list[sa.Column[object]]:
    return [
        sa.Column("adapter_id", sa.String(64), nullable=False),
        sa.Column("upstream_source_id", sa.String(96), nullable=False),
        sa.Column("authority_level", sa.String(32), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_hash", sa.String(64), nullable=False),
        sa.Column("transformation_version", sa.String(96), nullable=False),
        sa.Column("source_uri", sa.String(2048)),
        sa.Column("source_record_id", sa.String(255)),
        sa.Column("license_id", sa.String(96)),
    ]


def upgrade() -> None:
    op.create_table(
        "macro_series",
        sa.Column("series_id", sa.String(96), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("geography", sa.String(96), nullable=False),
        sa.Column("source_agency_id", sa.String(96), nullable=False),
        sa.Column("unit", sa.String(96), nullable=False),
        sa.Column("frequency", sa.String(32), nullable=False),
        sa.Column("seasonal_adjustment", sa.String(48), nullable=False),
    )
    op.create_table(
        "macro_observations",
        sa.Column("observation_id", sa.String(96), primary_key=True),
        sa.Column("raw_observation_id", sa.String(96), nullable=False),
        sa.Column("series_id", sa.String(96), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(38, 12), nullable=False),
        sa.Column("release_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("realtime_start", sa.Date(), nullable=False),
        sa.Column("realtime_end", sa.Date(), nullable=False),
        sa.Column("vintage_date", sa.Date(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("predecessor_observation_id", sa.String(96)),
        *_lineage_columns(),
        sa.ForeignKeyConstraint(["series_id"], ["macro_series.series_id"]),
    )
    op.create_index("ix_macro_observations_series_id", "macro_observations", ["series_id"])
    op.create_index(
        "ix_macro_observations_series_period_vintage",
        "macro_observations",
        ["series_id", "period_start", "realtime_start"],
    )
    op.create_table(
        "scheduled_events",
        sa.Column("event_version_id", sa.String(96), primary_key=True),
        sa.Column("event_id", sa.String(96), nullable=False),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("subject_id", sa.String(160), nullable=False),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_end", sa.DateTime(timezone=True)),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("predecessor_version_id", sa.String(96)),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_evidence_ids", sa.ARRAY(sa.String(96)), nullable=False),
        *_lineage_columns(),
    )
    op.create_index("ix_scheduled_events_event_id", "scheduled_events", ["event_id"])
    op.create_index(
        "ix_scheduled_events_event_version",
        "scheduled_events",
        ["event_id", "version"],
        unique=True,
    )
    op.create_table(
        "acquisition_plans",
        sa.Column("plan_id", sa.String(96), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("capability", sa.String(96), nullable=False),
        sa.Column("scope_id", sa.String(160), nullable=False),
        sa.Column("preferred_provider_ids", sa.ARRAY(sa.String(64)), nullable=False),
        sa.Column("cadence_kind", sa.String(32), nullable=False),
        sa.Column("interval_seconds", sa.BigInteger(), nullable=False),
        sa.Column("overlap_seconds", sa.BigInteger(), nullable=False),
        sa.Column("release_window_interval_seconds", sa.BigInteger(), nullable=False),
        sa.Column("release_window_before_seconds", sa.BigInteger(), nullable=False),
        sa.Column("release_window_after_seconds", sa.BigInteger(), nullable=False),
    )
    op.create_table(
        "acquisition_checkpoints",
        sa.Column("plan_id", sa.String(96), primary_key=True),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cursor", sa.Text()),
        sa.Column("watermark", sa.DateTime(timezone=True)),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_persisted_id", sa.String(96)),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_not_before", sa.DateTime(timezone=True)),
        sa.Column("rate_limit_reset_at", sa.DateTime(timezone=True)),
        sa.Column("lease_owner", sa.String(96)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(
            ["plan_id", "plan_version"],
            ["acquisition_plans.plan_id", "acquisition_plans.version"],
        ),
    )


def downgrade() -> None:
    op.drop_table("acquisition_checkpoints")
    op.drop_table("acquisition_plans")
    op.drop_index("ix_scheduled_events_event_version", table_name="scheduled_events")
    op.drop_index("ix_scheduled_events_event_id", table_name="scheduled_events")
    op.drop_table("scheduled_events")
    op.drop_index("ix_macro_observations_series_period_vintage", table_name="macro_observations")
    op.drop_index("ix_macro_observations_series_id", table_name="macro_observations")
    op.drop_table("macro_observations")
    op.drop_table("macro_series")
