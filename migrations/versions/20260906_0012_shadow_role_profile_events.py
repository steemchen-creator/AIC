"""Add append-only Shadow role profile audit events.

Revision ID: 20260906_0012
Revises: 20260906_0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260906_0012"
down_revision: str | None = "20260906_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shadow_role_profile_events",
        sa.Column("event_id", sa.String(80), primary_key=True),
        sa.Column(
            "group_id",
            sa.String(80),
            sa.ForeignKey("shadow_experiment_groups.group_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.String(80),
            sa.ForeignKey("shadow_experiment_members.account_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("manager_id", sa.String(80), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("previous_avatar_reference", sa.String(512), nullable=False),
        sa.Column("new_avatar_reference", sa.String(512), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )
    op.create_index(
        "ix_shadow_profile_event_manager_time",
        "shadow_role_profile_events",
        ["manager_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_shadow_profile_event_manager_time",
        table_name="shadow_role_profile_events",
    )
    op.drop_table("shadow_role_profile_events")
