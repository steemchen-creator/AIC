"""Add Shadow portfolio experiment manifests and immutable evidence.

Revision ID: 20260906_0011
Revises: 20260904_0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260906_0011"
down_revision: str | None = "20260904_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shadow_experiment_groups",
        sa.Column("group_id", sa.String(80), primary_key=True),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("policy_bundle_id", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recovery_projection", postgresql.JSONB(), nullable=False),
    )
    op.create_table(
        "shadow_experiment_members",
        sa.Column("account_id", sa.String(80), primary_key=True),
        sa.Column(
            "group_id",
            sa.String(80),
            sa.ForeignKey("shadow_experiment_groups.group_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("portfolio_id", sa.String(80), nullable=False, unique=True),
        sa.Column("portfolio_role", sa.String(24), nullable=False),
        sa.Column("role_identity", sa.String(24), nullable=False),
        sa.Column("manager_id", sa.String(80), nullable=False),
        sa.Column("decision_source_id", sa.String(160), nullable=False),
        sa.Column("policy_bundle_id", sa.String(80), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("group_id", "role_identity", name="uq_shadow_member_group_role"),
    )
    op.create_table(
        "shadow_group_sessions",
        sa.Column("group_session_id", sa.String(80), primary_key=True),
        sa.Column(
            "group_id",
            sa.String(80),
            sa.ForeignKey("shadow_experiment_groups.group_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("pit_cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("policy_bundle_id", sa.String(80), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("group_id", "trading_date", name="uq_shadow_session_group_date"),
    )
    op.create_table(
        "shadow_comparison_snapshots",
        sa.Column("comparison_id", sa.String(80), primary_key=True),
        sa.Column(
            "group_id",
            sa.String(80),
            sa.ForeignKey("shadow_experiment_groups.group_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "group_session_id",
            sa.String(80),
            sa.ForeignKey("shadow_group_sessions.group_session_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("policy_bundle_id", sa.String(80), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )
    op.create_table(
        "shadow_role_activities",
        sa.Column("activity_id", sa.String(80), primary_key=True),
        sa.Column(
            "group_id",
            sa.String(80),
            sa.ForeignKey("shadow_experiment_groups.group_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("group_session_id", sa.String(80), nullable=True),
        sa.Column(
            "account_id",
            sa.String(80),
            sa.ForeignKey("shadow_experiment_members.account_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("manager_id", sa.String(80), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("reason_code", sa.String(160), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )
    op.create_index(
        "ix_shadow_sessions_group_date",
        "shadow_group_sessions",
        ["group_id", "trading_date"],
    )
    op.create_index(
        "ix_shadow_comparisons_group_date",
        "shadow_comparison_snapshots",
        ["group_id", "trading_date"],
    )
    op.create_index(
        "ix_shadow_activity_group_time",
        "shadow_role_activities",
        ["group_id", "occurred_at"],
    )


def downgrade() -> None:
    for index_name, table_name in (
        ("ix_shadow_activity_group_time", "shadow_role_activities"),
        ("ix_shadow_comparisons_group_date", "shadow_comparison_snapshots"),
        ("ix_shadow_sessions_group_date", "shadow_group_sessions"),
    ):
        op.drop_index(index_name, table_name=table_name)
    for table_name in (
        "shadow_role_activities",
        "shadow_comparison_snapshots",
        "shadow_group_sessions",
        "shadow_experiment_members",
        "shadow_experiment_groups",
    ):
        op.drop_table(table_name)
