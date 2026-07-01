"""dedup marketplace_listings and add unique (connection_id, marketplace_sku)

Revision ID: 20260630120000
Revises: 20260630090000
Create Date: 2026-06-30 12:00:00

"""
from alembic import op

revision = "20260630120000"
down_revision = "20260630090000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Remove duplicate listings, keeping the earliest id per (connection, sku).
    op.execute(
        """
        DELETE FROM marketplace_listings
        WHERE id IN (
          SELECT id FROM (
            SELECT id, row_number() OVER (
              PARTITION BY connection_id, marketplace_sku ORDER BY id
            ) rn
            FROM marketplace_listings WHERE marketplace_sku IS NOT NULL
          ) t WHERE rn > 1)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_listing_conn_sku
        ON marketplace_listings (connection_id, marketplace_sku)
        WHERE marketplace_sku IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_listing_conn_sku")
