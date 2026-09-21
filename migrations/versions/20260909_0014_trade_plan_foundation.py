"""Add Trade Plan aggregate, revisions, directives, execution links and outcomes.

Revision ID: 20260909_0014
Revises: 20260906_0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260909_0014"
down_revision: str | None = "20260906_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trade_plans",
        sa.Column("plan_id", sa.String(80), primary_key=True),
        sa.Column("portfolio_id", sa.String(80), nullable=False),
        sa.Column("instrument_key", sa.String(128), nullable=False),
        sa.Column("instrument_type", sa.String(32), nullable=False),
        sa.Column("horizon", sa.String(32), nullable=False),
        sa.Column("style", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recovery_projection", postgresql.JSONB(), nullable=False),
    )
    op.create_index(
        "ix_trade_plans_pair_history",
        "trade_plans",
        ["portfolio_id", "instrument_key", "created_at", "plan_id"],
    )
    op.create_index(
        "uq_trade_plans_active_portfolio_instrument",
        "trade_plans",
        ["portfolio_id", "instrument_key"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_table(
        "trade_plan_revisions",
        sa.Column("plan_id", sa.String(80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("actor", sa.String(200), nullable=False),
        sa.Column("source", sa.String(255), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("plan_id", "version"),
        sa.ForeignKeyConstraint(["plan_id"], ["trade_plans.plan_id"], ondelete="RESTRICT"),
    )
    op.create_table(
        "trade_plan_directives",
        sa.Column("directive_id", sa.String(80), primary_key=True),
        sa.Column("plan_id", sa.String(80), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("directive_type", sa.String(24), nullable=False),
        sa.Column("decision_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("not_before", sa.DateTime(timezone=True)),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_id", "plan_version"],
            ["trade_plan_revisions.plan_id", "trade_plan_revisions.version"],
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_trade_plan_directives_plan_decision",
        "trade_plan_directives",
        ["plan_id", "decision_as_of", "directive_id"],
    )
    op.create_table(
        "trade_plan_execution_evidence",
        sa.Column("evidence_id", sa.String(80), primary_key=True),
        sa.Column("plan_id", sa.String(80), nullable=False),
        sa.Column("directive_id", sa.String(80), nullable=False, unique=True),
        sa.Column("order_id", sa.String(80), nullable=False),
        sa.Column("fill_id", sa.String(80)),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["trade_plans.plan_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["directive_id"], ["trade_plan_directives.directive_id"], ondelete="RESTRICT"
        ),
    )
    op.create_table(
        "trade_plan_outcomes",
        sa.Column("outcome_id", sa.String(80), primary_key=True),
        sa.Column("plan_id", sa.String(80), nullable=False, unique=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["trade_plans.plan_id"], ondelete="RESTRICT"),
    )


def downgrade() -> None:
    op.drop_table("trade_plan_outcomes")
    op.drop_table("trade_plan_execution_evidence")
    op.drop_index("ix_trade_plan_directives_plan_decision", table_name="trade_plan_directives")
    op.drop_table("trade_plan_directives")
    op.drop_table("trade_plan_revisions")
    op.drop_index("uq_trade_plans_active_portfolio_instrument", table_name="trade_plans")
    op.drop_index("ix_trade_plans_pair_history", table_name="trade_plans")
    op.drop_table("trade_plans")
