from contextlib import asynccontextmanager
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from app.core.config import settings
from app.core.database import engine, Base
from app.api.v1.router import api_router
import app.models  # ensure all models are imported before create_all


async def _init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Database tables created/verified.", flush=True)
    await _run_migrations()
    await _seed_admin()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await asyncio.wait_for(_init_db(), timeout=20)
    except asyncio.TimeoutError:
        print("WARNING: DB init timed out after 20s -- app will start without DB init.", flush=True)
    except Exception as e:
        print(f"WARNING: DB init failed: {e}", flush=True)
    yield


async def _seed_admin():
    """Create default admin user if not exists. Credentials from ADMIN_USERNAME / ADMIN_PASSWORD env vars."""
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole
    username = settings.ADMIN_USERNAME
    password = settings.ADMIN_PASSWORD
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(User).where(User.username == username))
            if not result.scalar_one_or_none():
                db.add(User(username=username, hashed_password=hash_password(password), role=UserRole.admin))
                await db.commit()
                print(f"Default admin user created ({username}/****).", flush=True)
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
        # unique index on username (partial -- ignores NULLs)
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_suppliers_username ON suppliers(username) WHERE username IS NOT NULL",
        # suppliers: portal toggle for self-service EasyPost label purchase
        "ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS can_buy_labels BOOLEAN NOT NULL DEFAULT FALSE",
        # supplier_products: short label for PDF overlays
        "ALTER TABLE supplier_products ADD COLUMN IF NOT EXISTS short_name VARCHAR(100)",
        # supplier_products: per-unit shipping dimensions for parcel auto-estimate
        "ALTER TABLE supplier_products ADD COLUMN IF NOT EXISTS weight NUMERIC(10, 3)",
        "ALTER TABLE supplier_products ADD COLUMN IF NOT EXISTS length NUMERIC(10, 2)",
        "ALTER TABLE supplier_products ADD COLUMN IF NOT EXISTS width NUMERIC(10, 2)",
        "ALTER TABLE supplier_products ADD COLUMN IF NOT EXISTS height NUMERIC(10, 2)",
    ]
    try:
        async with engine.begin() as conn:
            for sql in migrations:
                await conn.execute(text(sql))
        print("Migrations applied.", flush=True)
    except Exception as e:
        print(f"WARNING: migration error (non-fatal): {e}", flush=True)


app = FastAPI(
    title="Maga -- Supplier Fulfillment Platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
