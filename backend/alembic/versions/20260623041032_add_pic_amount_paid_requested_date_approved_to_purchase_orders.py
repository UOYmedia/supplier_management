"""add pic, amount_paid, requested_date, approved_by, approved_date to purchase_orders

Revision ID: 20260623041032
Revises:
Create Date: 2026-06-23 04:10:32

"""
from datetime import date
from alembic import op
import sqlalchemy as sa

revision = "20260623041032"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "purchase_orders",
        sa.Column("pic", sa.String(100), nullable=False, server_default=""),
    )
    op.add_column(
        "purchase_orders",
        sa.Column("amount_paid", sa.Float, nullable=False, server_default="0.0"),
    )
    op.add_column(
        "purchase_orders",
        sa.Column(
            "requested_date",
            sa.Date,
            nullable=False,
            server_default=sa.func.current_date(),
        ),
    )
    op.add_column(
        "purchase_orders",
        sa.Column("approved_by", sa.String(100), nullable=True),
    )
    op.add_column(
        "purchase_orders",
        sa.Column("approved_date", sa.Date, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("purchase_orders", "approved_date")
    op.drop_column("purchase_orders", "approved_by")
    op.drop_column("purchase_orders", "requested_date")
    op.drop_column("purchase_orders", "amount_paid")
    op.drop_column("purchase_orders", "pic")
