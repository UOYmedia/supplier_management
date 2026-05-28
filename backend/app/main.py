from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from app.core.config import settings
from app.core.database import engine, Base
from app.api.v1.router import api_router
import app.models  # ensure all models are imported before create_all


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("Database tables created/verified.", flush=True)
        # Column migrations for existing tables (idempotent)
        await _run_migrations()
        # Seed default admin user
        await _seed_admin()
    except Exception as e:
        print(f"WARNING: DB init failed (will retry on first request): {e}", flush=True)
    yield


async def _seed_admin():
    """Create or reset admin user. If ADMIN_PASSWORD env var is set, always update the password."""
    import os
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole
    try:
        override_password = os.environ.get("ADMIN_PASSWORD", "").strip()
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(User).where(User.username == "admin"))
            user = result.scalar_one_or_none()
            if user:
                if override_password:
                    user.hashed_password = hash_password(override_password)
                    await db.commit()
                    print("Admin password updated from ADMIN_PASSWORD env var.", flush=True)
            else:
                password = override_password or "admin"
                db.add(User(username="admin", hashed_password=hash_password(password), role=UserRole.admin))
                await db.commit()
                print(f"Default admin user created (admin/{password}).", flush=True)
    except Exception as e:
        print(f"WARNING: seed admin failed: {e}", flush=True)


async def _run_migrations():
    """Add new columns to existing tables without dropping data."""
    migrations = [
        # suppliers: address fields + portal auth
        "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS street1 VARCHAR(255)",
        "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS street2 VARCHAR(255)",
        "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS state VARCHAR(100)",
        "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS zipcode VARCHAR(20)",
        "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS username VARCHAR(100)",
        "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS hashed_password VARCHAR(255)",
        # unique index on username (partial — ignores NULLs)
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_suppliers_username ON suppliers(username) WHERE username IS NOT NULL",
        # shopify location sync
        "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS shopify_location_id VARCHAR(100)",
        "CREATE INDEX IF NOT EXISTS ix_suppliers_shopify_location_id ON suppliers(shopify_location_id) WHERE shopify_location_id IS NOT NULL",
        # Amazon MFN: base64 PDF label storage + wider label_url
        "ALTER TABLE shipping_labels ADD COLUMN IF NOT EXISTS label_data TEXT",
        "ALTER TABLE shipping_labels ALTER COLUMN label_url TYPE TEXT",
        # Allow marketplace listings without a linked shop product (for sync + mapping flow)
        "ALTER TABLE marketplace_listings ALTER COLUMN product_id DROP NOT NULL",
        # Supplier-level toggle: allow self-service EasyPost label purchase from the portal
        "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS can_buy_labels BOOLEAN NOT NULL DEFAULT FALSE",
        # Per-unit shipping dimensions on supplier catalog items (for parcel auto-estimate)
        "ALTER TABLE supplier_products ADD COLUMN IF NOT EXISTS weight NUMERIC(10, 3)",
        "ALTER TABLE supplier_products ADD COLUMN IF NOT EXISTS length NUMERIC(10, 2)",
        "ALTER TABLE supplier_products ADD COLUMN IF NOT EXISTS width NUMERIC(10, 2)",
        "ALTER TABLE supplier_products ADD COLUMN IF NOT EXISTS height NUMERIC(10, 2)",
    ]
    try:
        async with engine.begin() as conn:
            # Abort any DDL that waits more than 3 s for a lock — prevents startup hangs
            await conn.execute(text("SET lock_timeout = '3s'"))
            for sql in migrations:
                try:
                    await conn.execute(text(sql))
                except Exception as e:
                    print(f"WARNING: migration skipped ({e})", flush=True)
        print("Migrations applied.", flush=True)
    except Exception as e:
        print(f"WARNING: migration error (non-fatal): {e}", flush=True)


app = FastAPI(
    title="Maga — Supplier Fulfillment Platform",
    version="1.0.0",
    lifespan=lifespan,
)

_origins = list(filter(None, [
    settings.FRONTEND_URL,
    "http://localhost:3000",
]))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
