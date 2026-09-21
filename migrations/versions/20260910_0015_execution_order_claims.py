"""Add durable order claims and immutable authoritative execution receipts.

Revision ID: 20260910_0015
Revises: 20260909_0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260910_0015"
down_revision: str | None = "20260909_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "execution_order_claims",
        sa.Column("order_id", sa.String(80), primary_key=True),
        sa.Column("portfolio_id", sa.String(80), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claim", postgresql.JSONB(), nullable=False),
        sa.Column("receipt", postgresql.JSONB()),
    )
    op.create_index(
        "ix_execution_claims_portfolio", "execution_order_claims", ["portfolio_id", "requested_at"]
    )


def downgrade() -> None:
    op.drop_table("execution_order_claims")
