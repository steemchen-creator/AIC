"""Add forward paper trading and Champion portfolio evidence.

Revision ID: 20260904_0010
Revises: 20260903_0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260904_0010"
down_revision: str | None = "20260903_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "paper_accounts",
        sa.Column("account_id", sa.String(80), primary_key=True),
        sa.Column("portfolio_id", sa.String(80), nullable=False, unique=True),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("initial_capital", sa.Numeric(38, 10), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("capital_mode", sa.String(48), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_finalized_date", sa.Date(), nullable=True),
        sa.Column("recovery_projection", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint("initial_capital > 0", name="ck_paper_accounts_capital_positive"),
    )
    op.create_index("ix_paper_accounts_status", "paper_accounts", ["status", "updated_at"])

    op.create_table(
        "paper_sessions",
        sa.Column("session_id", sa.String(80), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(80),
            sa.ForeignKey("paper_accounts.account_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("planned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("policy_version", sa.String(128), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("account_id", "trading_date", name="uq_paper_session_account_date"),
    )
    op.create_index(
        "ix_paper_sessions_account_status",
        "paper_sessions",
        ["account_id", "status", "trading_date"],
    )

    op.create_table(
        "paper_account_state_events",
        sa.Column("event_id", sa.String(80), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(80),
            sa.ForeignKey("paper_accounts.account_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            sa.String(80),
            sa.ForeignKey("paper_sessions.session_id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("source_id", sa.String(160), nullable=False),
        sa.Column("operational_status", sa.String(48), nullable=False),
        sa.Column("from_status", sa.String(32), nullable=True),
        sa.Column("to_status", sa.String(32), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )
    op.create_index(
        "ix_paper_events_account_time",
        "paper_account_state_events",
        ["account_id", "occurred_at"],
    )

    op.create_table(
        "paper_order_intents",
        sa.Column("intent_id", sa.String(80), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(80),
            sa.ForeignKey("paper_accounts.account_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            sa.String(80),
            sa.ForeignKey("paper_sessions.session_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_trading_date", sa.Date(), nullable=False),
        sa.Column("instrument_key", sa.String(128), nullable=False),
        sa.Column("source_reference", sa.String(160), nullable=False),
        sa.Column("timing", sa.String(32), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )
    op.create_index(
        "ix_paper_intents_account_date",
        "paper_order_intents",
        ["account_id", "effective_trading_date"],
    )

    op.create_table(
        "paper_performance_snapshots",
        sa.Column("snapshot_id", sa.String(80), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(80),
            sa.ForeignKey("paper_accounts.account_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            sa.String(80),
            sa.ForeignKey("paper_sessions.session_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cash", sa.Numeric(38, 10), nullable=False),
        sa.Column("market_value", sa.Numeric(38, 10), nullable=False),
        sa.Column("nav", sa.Numeric(38, 10), nullable=False),
        sa.Column("benchmark_value", sa.Numeric(38, 10), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("account_id", "trading_date", name="uq_paper_performance_account_date"),
        sa.CheckConstraint("cash >= 0", name="ck_paper_performance_cash_non_negative"),
        sa.CheckConstraint("nav > 0", name="ck_paper_performance_nav_positive"),
    )
    op.create_index(
        "ix_paper_performance_account_time",
        "paper_performance_snapshots",
        ["account_id", "as_of"],
    )

    op.create_table(
        "paper_trade_episodes",
        sa.Column("episode_id", sa.String(80), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(80),
            sa.ForeignKey("paper_accounts.account_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("instrument_key", sa.String(128), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("net_pnl", sa.Numeric(38, 10), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
    )
    op.create_index(
        "ix_paper_episodes_account_close",
        "paper_trade_episodes",
        ["account_id", "closed_at"],
    )


def downgrade() -> None:
    for index_name, table_name in (
        ("ix_paper_episodes_account_close", "paper_trade_episodes"),
        ("ix_paper_performance_account_time", "paper_performance_snapshots"),
        ("ix_paper_intents_account_date", "paper_order_intents"),
        ("ix_paper_events_account_time", "paper_account_state_events"),
        ("ix_paper_sessions_account_status", "paper_sessions"),
        ("ix_paper_accounts_status", "paper_accounts"),
    ):
        op.drop_index(index_name, table_name=table_name)
        op.drop_table(table_name)
