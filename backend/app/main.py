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
        # shipping_labels: address JSON + timestamp
        "ALTER TABLE shipping_labels ADD COLUMN IF NOT EXISTS from_address JSONB",
        "ALTER TABLE shipping_labels ADD COLUMN IF NOT EXISTS to_address JSONB",
        "ALTER TABLE shipping_labels ADD COLUMN IF NOT EXISTS purchased_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
        "ALTER TABLE shipping_labels ADD COLUMN IF NOT EXISTS cost NUMERIC(8,2) NOT NULL DEFAULT 0",
        "ALTER TABLE shipping_labels ADD COLUMN IF NOT EXISTS service VARCHAR(100)",
        # Convert JSON → JSONB to support DISTINCT queries (JSON has no equality operator)
        "ALTER TABLE shipping_labels ALTER COLUMN from_address TYPE JSONB USING from_address::text::jsonb",
        "ALTER TABLE shipping_labels ALTER COLUMN to_address TYPE JSONB USING to_address::text::jsonb",
        "ALTER TABLE orders ALTER COLUMN shipping_address TYPE JSONB USING shipping_address::text::jsonb",
        # Allow marketplace listings without a linked shop product (for sync + mapping flow)
        "ALTER TABLE marketplace_listings ALTER COLUMN product_id DROP NOT NULL",
        # orders: new columns added after initial deploy
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS connection_id INTEGER REFERENCES marketplace_connections(id)",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS buyer_email VARCHAR(255)",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
        # order_line_items: columns added after initial deploy
        "ALTER TABLE order_line_items ADD COLUMN IF NOT EXISTS listing_id INTEGER REFERENCES marketplace_listings(id)",
        "ALTER TABLE order_line_items ADD COLUMN IF NOT EXISTS external_line_item_id VARCHAR(255)",
        "ALTER TABLE order_line_items ADD COLUMN IF NOT EXISTS base_cost NUMERIC(10,2) NOT NULL DEFAULT 0",
        "ALTER TABLE order_line_items ADD COLUMN IF NOT EXISTS label_id INTEGER REFERENCES shipping_labels(id)",
        "ALTER TABLE order_line_items ADD COLUMN IF NOT EXISTS fulfilled_at TIMESTAMP WITH TIME ZONE",
        # Supplier-level toggle: allow self-service EasyPost label purchase from the portal
        "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS can_buy_labels BOOLEAN NOT NULL DEFAULT FALSE",
        # Per-unit shipping dimensions on supplier catalog items (for parcel auto-estimate)
        "ALTER TABLE supplier_products ADD COLUMN IF NOT EXISTS weight NUMERIC(10, 3)",
        "ALTER TABLE supplier_products ADD COLUMN IF NOT EXISTS length NUMERIC(10, 2)",
        "ALTER TABLE supplier_products ADD COLUMN IF NOT EXISTS width NUMERIC(10, 2)",
        "ALTER TABLE supplier_products ADD COLUMN IF NOT EXISTS height NUMERIC(10, 2)",
        # Product thumbnail for supplier catalog
        "ALTER TABLE supplier_products ADD COLUMN IF NOT EXISTS image_url TEXT",
        # Timestamps on supplier catalog items
        "ALTER TABLE supplier_products ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
        "ALTER TABLE supplier_products ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()",
        # product_components table (combo/set product support)
        """CREATE TABLE IF NOT EXISTS product_components (
            id SERIAL PRIMARY KEY,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            supplier_product_id INTEGER NOT NULL REFERENCES supplier_products(id) ON DELETE CASCADE,
            quantity INTEGER NOT NULL DEFAULT 1,
            UNIQUE(product_id, supplier_product_id)
        )""",
        # order_fulfillment_items table
        """CREATE TABLE IF NOT EXISTS order_fulfillment_items (
            id SERIAL PRIMARY KEY,
            order_line_item_id INTEGER NOT NULL REFERENCES order_line_items(id) ON DELETE CASCADE,
            supplier_product_id INTEGER NOT NULL REFERENCES supplier_products(id),
            quantity INTEGER NOT NULL DEFAULT 1,
            fulfill_status VARCHAR(50) NOT NULL DEFAULT 'unfulfilled',
            tracking_number VARCHAR(255),
            label_id INTEGER REFERENCES shipping_labels(id),
            fulfilled_at TIMESTAMP WITH TIME ZONE
        )""",
        "ALTER TABLE order_fulfillment_items ADD COLUMN IF NOT EXISTS label_id INTEGER REFERENCES shipping_labels(id)",
    ]
    # ALTER TYPE must run outside a transaction (autocommit)
    try:
        async with engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn.execute(text("ALTER TYPE fulfillstatus ADD VALUE IF NOT EXISTS 'drop_off' AFTER 'pending'"))
    except Exception as e:
        print(f"WARNING: enum migration skipped ({e})", flush=True)

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


@app.get("/version")
async def version():
    return {"version": "2026-06-01-all-carriers"}
