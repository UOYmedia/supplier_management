"""
One-shot DB initializer: create all tables + seed admin user.

Usage (from /app inside Railway shell):
  python scripts/init_db.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.core.database import engine, Base
from app.core.config import settings
import app.models  # registers all models with Base


async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("All tables created/verified.", flush=True)


async def run_migrations():
    migrations = [
        "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS street1 VARCHAR(255)",
        "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS street2 VARCHAR(255)",
        "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS state VARCHAR(100)",
        "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS zipcode VARCHAR(20)",
        "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS username VARCHAR(100)",
        "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS hashed_password VARCHAR(255)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_suppliers_username ON suppliers(username) WHERE username IS NOT NULL",
        "ALTER TABLE shipping_labels ADD COLUMN IF NOT EXISTS refunded_at TIMESTAMPTZ",
        # purchase_orders table (created by create_all; these guard existing DBs)
        """
        CREATE TABLE IF NOT EXISTS purchase_orders (
            id SERIAL PRIMARY KEY,
            supplier VARCHAR(20) NOT NULL,
            sku VARCHAR(255) NOT NULL,
            qty_ordered INTEGER NOT NULL,
            qty_available INTEGER NOT NULL DEFAULT 0,
            unit_cost NUMERIC(10,2) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
            po_number VARCHAR(100) NOT NULL,
            created_date DATE NOT NULL,
            paid_date DATE,
            notes TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_purchase_orders_supplier ON purchase_orders(supplier)",
        "CREATE INDEX IF NOT EXISTS ix_purchase_orders_sku ON purchase_orders(sku)",
        "CREATE INDEX IF NOT EXISTS ix_purchase_orders_created_date ON purchase_orders(created_date)",
        "CREATE INDEX IF NOT EXISTS ix_purchase_orders_po_number ON purchase_orders(po_number)",
        # qty_available column for existing purchase_orders tables
        "ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS qty_available INTEGER NOT NULL DEFAULT 0",
    ]
    async with engine.begin() as conn:
        for sql in migrations:
            await conn.execute(text(sql))
    print("Column migrations applied.", flush=True)


async def seed_admin():
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    username = settings.ADMIN_USERNAME
    password = settings.ADMIN_PASSWORD

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.username == username))
        existing = result.scalar_one_or_none()
        if existing:
            print(f"Admin user '{username}' already exists -- skipping.", flush=True)
        else:
            db.add(User(username=username, hashed_password=hash_password(password), role=UserRole.admin))
            await db.commit()
            print(f"Admin user '{username}' created.", flush=True)


async def main():
    print(f"Connecting to: {settings.DATABASE_URL[:40]}...", flush=True)
    await create_tables()
    await run_migrations()
    await seed_admin()
    print("Done.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
