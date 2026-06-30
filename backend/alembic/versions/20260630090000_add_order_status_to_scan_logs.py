"""add order_status to scan_logs

Revision ID: 20260630090000
Revises: 20260623041032
Create Date: 2026-06-30 09:00:00

"""
from alembic import op
import sqlalchemy as sa

revision = "20260630090000"
down_revision = "20260623041032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scan_logs",
        sa.Column("order_status", sa.String(60), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scan_logs", "order_status")
