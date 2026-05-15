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
    """Create default admin user if no users exist."""
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(User).where(User.username == "admin"))
            if not result.scalar_one_or_none():
                db.add(User(username="admin", hashed_password=hash_password("admin"), role=UserRole.admin))
                await db.commit()
                print("Default admin user created (admin/admin).", flush=True)
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
    ]
    try:
        async with engine.begin() as conn:
            for sql in migrations:
                await conn.execute(text(sql))
        print("Migrations applied.", flush=True)
    except Exception as e:
        print(f"WARNING: migration error (non-fatal): {e}", flush=True)


app = FastAPI(
    title="Maga — Supplier Fulfillment Platform",
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
