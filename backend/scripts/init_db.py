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
