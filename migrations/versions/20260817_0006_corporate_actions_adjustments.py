"""Create corporate actions and adjustment factors."""

import sqlalchemy as sa
from alembic import op

revision = "20260817_0006"
down_revision = "20260817_0005"
branch_labels = None
depends_on = None


def _source_columns() -> list[sa.Column]:
    return [
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_id", sa.String(255), nullable=False),
        sa.Column("source_record_id", sa.String(255)),
        sa.Column("source_uri", sa.String(2048)),
        sa.Column("raw_payload_hash", sa.String(64), nullable=False),
        sa.Column("transformation_version", sa.String(255), nullable=False),
    ]


def _instrument_columns() -> list[sa.Column]:
    return [
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("instrument_type", sa.String(32), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "adjustment_factors",
        sa.Column("factor_id", sa.String(128), primary_key=True),
        *_instrument_columns(),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("factor", sa.Numeric(38, 18), nullable=False),
        sa.Column("factor_version", sa.String(128), nullable=False),
        *_source_columns(),
        sa.CheckConstraint("factor > 0", name="ck_adjustment_factor_positive"),
        sa.UniqueConstraint("market", "symbol", "trading_date", name="uq_adjustment_factor_day"),
    )
    op.create_index(
        "ix_adjustment_factor_range", "adjustment_factors", ["market", "symbol", "trading_date"]
    )
    op.create_table(
        "corporate_actions",
        sa.Column("action_id", sa.String(160), primary_key=True),
        *_instrument_columns(),
        sa.Column("action_type", sa.String(48), nullable=False),
        sa.Column("record_date", sa.Date()),
        sa.Column("ex_date", sa.Date()),
        sa.Column("pay_date", sa.Date()),
        sa.Column("effective_date", sa.Date()),
        sa.Column("cash_amount", sa.Numeric(38, 18)),
        sa.Column("share_ratio", sa.Numeric(38, 18)),
        sa.Column("rights_price", sa.Numeric(38, 18)),
        *_source_columns(),
        sa.CheckConstraint(
            "cash_amount IS NULL OR cash_amount >= 0", name="ck_action_cash_nonnegative"
        ),
        sa.CheckConstraint(
            "share_ratio IS NULL OR share_ratio >= 0", name="ck_action_ratio_nonnegative"
        ),
        sa.CheckConstraint(
            "rights_price IS NULL OR rights_price >= 0", name="ck_action_rights_nonnegative"
        ),
    )
    op.create_index(
        "ix_corporate_action_range", "corporate_actions", ["market", "symbol", "effective_date"]
    )


def downgrade() -> None:
    op.drop_index("ix_corporate_action_range", table_name="corporate_actions")
    op.drop_table("corporate_actions")
    op.drop_index("ix_adjustment_factor_range", table_name="adjustment_factors")
    op.drop_table("adjustment_factors")
