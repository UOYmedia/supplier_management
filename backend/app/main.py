from contextlib import asynccontextmanager
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from app.core.config import settings
from app.core.database import engine, Base
from app.api.v1.router import api_router
from app.core.scheduler import scheduler, fill_short_names
import app.models  # ensure all models are imported before create_all


async def _init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Database tables created/verified.", flush=True)
    await _run_migrations()
    await _seed_admin()


async def _auto_sync_loop():
    """Sync orders for all active connections every 60 minutes.
    First run happens 5 minutes after server start."""
    print("Auto-sync: started (first run in 5 minutes)", flush=True)
    try:
        await asyncio.sleep(5 * 60)
    except asyncio.CancelledError:
        return

    while True:
        try:
            from sqlalchemy import select as _select
            from app.core.database import AsyncSessionLocal
            from app.models.marketplace import MarketplaceConnection, ConnectionStatus

            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    _select(MarketplaceConnection).where(
                        MarketplaceConnection.status == ConnectionStatus.active
                    )
                )
                conn_ids = [c.id for c in result.scalars().all()]

            print(f"Auto-sync: syncing {len(conn_ids)} active connection(s)...", flush=True)
            from app.api.v1.marketplace import _do_sync_orders
            for conn_id in conn_ids:
                print(f"Auto-sync: syncing connection {conn_id}...", flush=True)
                try:
                    await _do_sync_orders(conn_id)
                except Exception as e:
                    print(f"Auto-sync: connection {conn_id} failed — {e}", flush=True)
            print(f"Auto-sync done: {len(conn_ids)} connection(s) processed", flush=True)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"Auto-sync: unexpected error — {e}", flush=True)

        try:
            await asyncio.sleep(60 * 60)
        except asyncio.CancelledError:
            return


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await asyncio.wait_for(_init_db(), timeout=20)
    except asyncio.TimeoutError:
        print("WARNING: DB init timed out after 20s -- app will start without DB init.", flush=True)
    except Exception as e:
        print(f"WARNING: DB init failed: {e}", flush=True)

    sync_task = asyncio.create_task(_auto_sync_loop())
    scheduler.start()
    async def _delayed_fill():
        await asyncio.sleep(30)  # wait 30s for DB to be ready
        await fill_short_names()
    asyncio.create_task(_delayed_fill())
    yield
    sync_task.cancel()
    try:
        await sync_task
    except asyncio.CancelledError:
        pass
    print("Auto-sync: stopped", flush=True)
    scheduler.shutdown(wait=False)


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
    """Add new columns/indexes to existing tables without dropping data.
    Each statement runs in its own transaction so a failure on one step
    does not prevent the rest from applying."""
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
        # shipping_labels: refund timestamp
        "ALTER TABLE shipping_labels ADD COLUMN IF NOT EXISTS refunded_at TIMESTAMPTZ",
        # order_line_items: label tracking fields
        "ALTER TABLE order_line_items ADD COLUMN IF NOT EXISTS label_id INTEGER REFERENCES shipping_labels(id)",
        "ALTER TABLE order_line_items ADD COLUMN IF NOT EXISTS tracking_number VARCHAR(255)",
        "ALTER TABLE order_line_items ADD COLUMN IF NOT EXISTS fulfilled_at TIMESTAMPTZ",
        # order_line_items: Amazon ASIN identifier
        "ALTER TABLE order_line_items ADD COLUMN IF NOT EXISTS asin VARCHAR(20)",
        # order_fulfillment_items: label tracking fields
        "ALTER TABLE order_fulfillment_items ADD COLUMN IF NOT EXISTS tracking_number VARCHAR(255)",
        "ALTER TABLE order_fulfillment_items ADD COLUMN IF NOT EXISTS label_id INTEGER REFERENCES shipping_labels(id)",
        "ALTER TABLE order_fulfillment_items ADD COLUMN IF NOT EXISTS fulfilled_at TIMESTAMPTZ",
        # convert native PostgreSQL ENUM columns to VARCHAR so asyncpg ::VARCHAR binding works
        # (older DBs had native ENUM types; models now use String(50))
        "ALTER TABLE order_fulfillment_items ALTER COLUMN fulfill_status TYPE VARCHAR(50) USING fulfill_status::text",
        "ALTER TABLE order_line_items ALTER COLUMN fulfill_status TYPE VARCHAR(50) USING fulfill_status::text",
        "ALTER TABLE orders ALTER COLUMN status TYPE VARCHAR(50) USING status::text",
        # daily_balances: manual deposit ("nạp thêm") recorded per day
        "ALTER TABLE daily_balances ADD COLUMN IF NOT EXISTS top_up NUMERIC(12, 2) NOT NULL DEFAULT 0",
        # daily_balances: manual COGS for externally-fulfilled (Amazon) orders without recorded cost
        "ALTER TABLE daily_balances ADD COLUMN IF NOT EXISTS external_cogs NUMERIC(12, 2) NOT NULL DEFAULT 0",
        # purchase_orders: PIC-driven request workflow fields
        "ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS pic VARCHAR(100) NOT NULL DEFAULT ''",
        "ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS amount_paid FLOAT NOT NULL DEFAULT 0.0",
        "ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS requested_date DATE NOT NULL DEFAULT CURRENT_DATE",
        "ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS approved_by VARCHAR(100)",
        "ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS approved_date DATE",
        "ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS record_type VARCHAR(10) NOT NULL DEFAULT 'daily'",
        # Backfill: rows with a non-empty pic were created as requests, not daily POs
        "UPDATE purchase_orders SET record_type = 'request' WHERE pic IS NOT NULL AND pic != '' AND record_type = 'daily'",
    ]
    ok, failed = 0, 0
    for sql in migrations:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(sql))
            ok += 1
        except Exception as e:
            failed += 1
            print(f"WARNING: migration skipped ({e.__class__.__name__}): {sql[:60]}... — {e}", flush=True)
    print(f"Migrations done: {ok} applied, {failed} skipped.", flush=True)


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
