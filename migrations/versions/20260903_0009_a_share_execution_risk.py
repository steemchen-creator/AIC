"""Add A-share execution, settlement, and risk evidence.

Revision ID: 20260903_0009
Revises: 20260820_0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260903_0009"
down_revision: str | None = "20260820_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "risk_decisions",
        sa.Column("risk_decision_id", sa.String(80), primary_key=True),
        sa.Column("portfolio_id", sa.String(80), nullable=False),
        sa.Column("order_id", sa.String(80), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reason_codes", postgresql.JSONB(), nullable=False),
        sa.Column("policy_version", sa.String(128), nullable=False),
        sa.Column("execution_policy_versions", postgresql.JSONB(), nullable=False),
        sa.Column("input_summary", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_risk_decisions_portfolio", "risk_decisions", ["portfolio_id", "as_of"])
    op.create_table(
        "execution_risk_snapshots",
        sa.Column("snapshot_id", sa.String(80), primary_key=True),
        sa.Column("portfolio_id", sa.String(80), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("nav", sa.Numeric(38, 10), nullable=False),
        sa.Column("cash", sa.Numeric(38, 10), nullable=False),
        sa.Column("gross_exposure", sa.Numeric(38, 10), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )
    op.create_index(
        "ix_execution_risk_snapshots_portfolio",
        "execution_risk_snapshots",
        ["portfolio_id", "as_of"],
    )
    op.create_table(
        "settlement_rollovers",
        sa.Column("event_id", sa.String(80), primary_key=True),
        sa.Column("portfolio_id", sa.String(80), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_quantity", sa.Numeric(38, 10), nullable=False),
        sa.Column("policy_version", sa.String(128), nullable=False),
    )
    op.create_index(
        "ix_settlement_rollovers_portfolio",
        "settlement_rollovers",
        ["portfolio_id", "trading_date"],
    )
    op.create_table(
        "settlement_position_evidence",
        sa.Column("evidence_id", sa.String(160), primary_key=True),
        sa.Column("portfolio_id", sa.String(80), nullable=False),
        sa.Column("order_id", sa.String(80), nullable=False),
        sa.Column("instrument_key", sa.String(128), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_quantity", sa.Numeric(38, 10), nullable=False),
        sa.Column("sellable_quantity", sa.Numeric(38, 10), nullable=False),
        sa.Column("today_bought_quantity", sa.Numeric(38, 10), nullable=False),
        sa.Column("policy_version", sa.String(128), nullable=False),
    )
    op.create_index(
        "ix_settlement_position_portfolio",
        "settlement_position_evidence",
        ["portfolio_id", "as_of"],
    )
    op.create_table(
        "execution_audit_events",
        sa.Column("event_id", sa.String(80), primary_key=True),
        sa.Column("portfolio_id", sa.String(80), nullable=False),
        sa.Column("order_id", sa.String(80), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("source_id", sa.String(160), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )
    op.create_index(
        "ix_execution_audit_events_portfolio",
        "execution_audit_events",
        ["portfolio_id", "occurred_at"],
    )


def downgrade() -> None:
    for index_name, table_name in (
        ("ix_execution_audit_events_portfolio", "execution_audit_events"),
        ("ix_settlement_position_portfolio", "settlement_position_evidence"),
        ("ix_settlement_rollovers_portfolio", "settlement_rollovers"),
        ("ix_execution_risk_snapshots_portfolio", "execution_risk_snapshots"),
        ("ix_risk_decisions_portfolio", "risk_decisions"),
    ):
        op.drop_index(index_name, table_name=table_name)
        op.drop_table(table_name)
