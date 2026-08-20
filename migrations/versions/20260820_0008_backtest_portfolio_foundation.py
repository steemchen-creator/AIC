"""Add deterministic backtest and portfolio accounting tables.

Revision ID: 20260820_0008
Revises: 20260817_0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260820_0008"
down_revision: str | None = "20260817_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column("run_id", sa.String(80), primary_key=True),
        sa.Column("portfolio_id", sa.String(80), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("initial_capital", sa.Numeric(38, 10), nullable=False),
        sa.Column("data_policy_version", sa.String(128), nullable=False),
        sa.Column("fee_policy_version", sa.String(128), nullable=False),
        sa.Column("slippage_policy_version", sa.String(128), nullable=False),
        sa.Column("execution_policy_version", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
    )
    for name, key, timestamp, extra in (
        (
            "backtest_orders",
            "order_id",
            "created_at",
            (
                sa.Column("portfolio_id", sa.String(80), nullable=False),
                sa.Column("instrument_key", sa.String(128), nullable=False),
            ),
        ),
        (
            "backtest_fills",
            "fill_id",
            "executed_at",
            (sa.Column("order_id", sa.String(80), nullable=False),),
        ),
        (
            "backtest_audit_events",
            "event_id",
            "occurred_at",
            (
                sa.Column("portfolio_id", sa.String(80), nullable=False),
                sa.Column("event_type", sa.String(64), nullable=False),
                sa.Column("source_id", sa.String(160), nullable=False),
            ),
        ),
    ):
        op.create_table(
            name,
            sa.Column(key, sa.String(80), primary_key=True),
            sa.Column(
                "run_id",
                sa.String(80),
                sa.ForeignKey("backtest_runs.run_id", ondelete="CASCADE"),
                nullable=False,
            ),
            *extra,
            sa.Column(timestamp, sa.DateTime(timezone=True), nullable=False),
            sa.Column("payload", postgresql.JSONB(), nullable=False),
        )
        op.create_index(f"ix_{name}_run", name, ["run_id", timestamp])
    op.create_table(
        "portfolio_cash_ledger",
        sa.Column("entry_id", sa.String(80), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(80),
            sa.ForeignKey("backtest_runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("portfolio_id", sa.String(80), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_type", sa.String(32), nullable=False),
        sa.Column("amount", sa.Numeric(38, 10), nullable=False),
        sa.Column("balance_after", sa.Numeric(38, 10), nullable=False),
        sa.Column("source_id", sa.String(80), nullable=False),
    )
    op.create_index(
        "ix_portfolio_cash_ledger_run", "portfolio_cash_ledger", ["run_id", "occurred_at"]
    )
    op.create_table(
        "portfolio_nav_snapshots",
        sa.Column("snapshot_id", sa.String(160), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(80),
            sa.ForeignKey("backtest_runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("portfolio_id", sa.String(80), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cash", sa.Numeric(38, 10), nullable=False),
        sa.Column("market_value", sa.Numeric(38, 10), nullable=False),
        sa.Column("nav", sa.Numeric(38, 10), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_portfolio_nav_run", "portfolio_nav_snapshots", ["run_id", "as_of"])


def downgrade() -> None:
    op.drop_index("ix_portfolio_nav_run", table_name="portfolio_nav_snapshots")
    op.drop_table("portfolio_nav_snapshots")
    op.drop_index("ix_portfolio_cash_ledger_run", table_name="portfolio_cash_ledger")
    op.drop_table("portfolio_cash_ledger")
    for name in ("backtest_audit_events", "backtest_fills", "backtest_orders"):
        op.drop_index(f"ix_{name}_run", table_name=name)
        op.drop_table(name)
    op.drop_table("backtest_runs")
