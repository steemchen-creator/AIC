"""Expand canonical record identity storage to match deterministic IDs."""

import sqlalchemy as sa
from alembic import op

revision = "20260814_0002"
down_revision = "20260813_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "canonical_daily_bars",
        "record_id",
        existing_type=sa.String(64),
        type_=sa.String(80),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "canonical_daily_bars",
        "record_id",
        existing_type=sa.String(80),
        type_=sa.String(64),
        existing_nullable=False,
    )
