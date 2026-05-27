from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.marketplace import MarketplaceConnection, MarketplaceListing, MarketplaceType, ConnectionStatus
from app.models.product import Product
from app.schemas.marketplace import (
    ConnectionCreate, ConnectionUpdate, ConnectionOut,
    ListingCreate, ListingUpdate, ListingOut,
    PushListingRequest, SyncResult
)
from app.integrations.amazon.sync import AmazonSync
from app.integrations.shopify.sync import ShopifySync
from datetime import datetime, timezone

router = APIRouter(prefix="/marketplace", tags=["marketplace"])


@router.get("/connections", response_model=list[ConnectionOut])
async def list_connections(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MarketplaceConnection))
    return result.scalars().all()


@router.post("/connections", response_model=ConnectionOut, status_code=201)
async def create_connection(body: ConnectionCreate, db: AsyncSession = Depends(get_db)):
    conn = MarketplaceConnection(**body.model_dump())
    db.add(conn)
    await db.commit()
    await db.refresh(conn)
    return conn


@router.get("/connections/{conn_id}", response_model=ConnectionOut)
async def get_connection(conn_id: int, db: AsyncSession = Depends(get_db)):
    return await _get_conn_or_404(conn_id, db)


@router.patch("/connections/{conn_id}", response_model=ConnectionOut)
async def update_connection(conn_id: int, body: ConnectionUpdate, db: AsyncSession = Depends(get_db)):
    conn = await _get_conn_or_404(conn_id, db)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(conn, k, v)
    await db.commit()
    await db.refresh(conn)
    return conn


@router.delete("/connections/{conn_id}", status_code=204)
async def delete_connection(conn_id: int, db: AsyncSession = Depends(get_db)):
    conn = await _get_conn_or_404(conn_id, db)
    await db.delete(conn)
    await db.commit()


@router.post("/connections/{conn_id}/test", response_model=dict)
async def test_connection(conn_id: int, db: AsyncSession = Depends(get_db)):
    conn = await _get_conn_or_404(conn_id, db)
    try:
        syncer = _get_syncer(conn)
        ok = await syncer.test_connection()
        conn.status = ConnectionStatus.active if ok else ConnectionStatus.error
        conn.error_message = None if ok else "Connection test failed"
    except Exception as e:
        conn.status = ConnectionStatus.error
        conn.error_message = str(e)
        ok = False
    await db.commit()
    return {"success": ok, "status": conn.status}


# --- Listings ---

@router.get("/listings", response_model=list[ListingOut])
async def list_listings(
    connection_id: int | None = None,
    product_id: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    q = select(MarketplaceListing)
    if connection_id:
        q = q.where(MarketplaceListing.connection_id == connection_id)
    if product_id:
        q = q.where(MarketplaceListing.product_id == product_id)
    result = await db.execute(q)
    listings = result.scalars().all()
    out = []
    for l in listings:
        p = await db.get(Product, l.product_id)
        data = {c.name: getattr(l, c.name) for c in l.__table__.columns}
        data["product_name"] = p.name if p else None
        data["product_sku"] = p.sku if p else None
        out.append(ListingOut(**data))
    return out


@router.post("/listings", response_model=ListingOut, status_code=201)
async def create_listing(body: ListingCreate, db: AsyncSession = Depends(get_db)):
    listing = MarketplaceListing(**body.model_dump())
    db.add(listing)
    await db.commit()
    await db.refresh(listing)
    p = await db.get(Product, listing.product_id)
    data = {c.name: getattr(listing, c.name) for c in listing.__table__.columns}
    data["product_name"] = p.name if p else None
    data["product_sku"] = p.sku if p else None
    return ListingOut(**data)


@router.patch("/listings/{listing_id}", response_model=ListingOut)
async def update_listing(listing_id: int, body: ListingUpdate, db: AsyncSession = Depends(get_db)):
    listing = await db.get(MarketplaceListing, listing_id)
    if not listing:
        raise HTTPException(404, "Listing not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(listing, k, v)
    await db.commit()
    await db.refresh(listing)
    p = await db.get(Product, listing.product_id)
    data = {c.name: getattr(listing, c.name) for c in listing.__table__.columns}
    data["product_name"] = p.name if p else None
    data["product_sku"] = p.sku if p else None
    return ListingOut(**data)


# --- Push to marketplace ---

@router.post("/push", response_model=SyncResult)
async def push_to_marketplace(
    body: PushListingRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    conn = await _get_conn_or_404(body.connection_id, db)
    syncer = _get_syncer(conn)
    result = SyncResult()

    for product_id in body.product_ids:
        product = await db.get(Product, product_id)
        if not product:
            result.failed += 1
            result.errors.append(f"Product {product_id} not found")
            continue
        try:
            external_id = await syncer.push_product(product, price=body.price)
            existing = await db.execute(
                select(MarketplaceListing).where(
                    MarketplaceListing.product_id == product_id,
                    MarketplaceListing.connection_id == body.connection_id,
                )
            )
            listing = existing.scalar_one_or_none()
            if listing:
                listing.external_id = external_id
                listing.synced_at = datetime.now(timezone.utc)
            else:
                db.add(MarketplaceListing(
                    product_id=product_id,
                    connection_id=body.connection_id,
                    external_id=external_id,
                    title=product.name,
                    price=body.price,
                    synced_at=datetime.now(timezone.utc),
                ))
            result.success += 1
        except Exception as e:
            result.failed += 1
            result.errors.append(f"Product {product_id}: {e}")

    conn.last_synced_at = datetime.now(timezone.utc)
    await db.commit()
    return result


# --- Sync orders from marketplace ---

@router.post("/connections/{conn_id}/sync-locations")
async def sync_locations(conn_id: int, db: AsyncSession = Depends(get_db)):
    """Pull Shopify locations and upsert as Suppliers (Shopify only)."""
    conn = await _get_conn_or_404(conn_id, db)
    if conn.marketplace != MarketplaceType.shopify:
        raise HTTPException(400, "Location sync is only supported for Shopify connections")
    syncer = ShopifySync(conn)
    result = await syncer.sync_locations(db)
    conn.last_synced_at = datetime.now(timezone.utc)
    await db.commit()
    return result


@router.post("/connections/{conn_id}/sync-orders")
async def sync_orders(
    conn_id: int,
    background_tasks: BackgroundTasks,
    created_after: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Sync orders from marketplace. Pass created_after (ISO8601) for full re-sync."""
    conn = await _get_conn_or_404(conn_id, db)
    background_tasks.add_task(_do_sync_orders, conn_id, created_after)
    return {"message": "Order sync started in background"}


@router.post("/connections/{conn_id}/sync-products")
async def sync_products(conn_id: int, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    conn = await _get_conn_or_404(conn_id, db)
    background_tasks.add_task(_do_sync_products, conn_id)
    return {"message": "Product sync started in background"}


@router.post("/connections/{conn_id}/sync-listings")
async def sync_listings(conn_id: int, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """Pull active listings from Amazon (FBA inventory) into local MarketplaceListing records."""
    conn = await _get_conn_or_404(conn_id, db)
    if conn.marketplace != MarketplaceType.amazon:
        raise HTTPException(400, "Listing sync is only supported for Amazon connections")
    background_tasks.add_task(_do_sync_listings, conn_id)
    return {"message": "Listing sync started in background"}


async def _do_sync_orders(conn_id: int, created_after: str | None = None):
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        conn = await db.get(MarketplaceConnection, conn_id)
        if not conn:
            return
        syncer = _get_syncer(conn)
        if conn.marketplace == MarketplaceType.amazon:
            from app.integrations.amazon.sync import AmazonSync
            await syncer.sync_orders(db, created_after=created_after)
        else:
            await syncer.sync_orders(db)
        conn.last_synced_at = datetime.now(timezone.utc)
        await db.commit()


async def _do_sync_listings(conn_id: int):
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        conn = await db.get(MarketplaceConnection, conn_id)
        if not conn:
            return
        from app.integrations.amazon.sync import AmazonSync
        syncer = AmazonSync(conn)
        await syncer.sync_listings(db)
        conn.last_synced_at = datetime.now(timezone.utc)
        await db.commit()


async def _do_sync_products(conn_id: int):
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        conn = await db.get(MarketplaceConnection, conn_id)
        if not conn:
            return
        syncer = _get_syncer(conn)
        await syncer.sync_products(db)
        conn.last_synced_at = datetime.now(timezone.utc)
        await db.commit()


# --- Helpers ---

def _get_syncer(conn: MarketplaceConnection):
    if conn.marketplace == MarketplaceType.amazon:
        return AmazonSync(conn)
    elif conn.marketplace == MarketplaceType.shopify:
        return ShopifySync(conn)
    raise HTTPException(400, f"Unsupported marketplace: {conn.marketplace}")


async def _get_conn_or_404(conn_id: int, db: AsyncSession) -> MarketplaceConnection:
    conn = await db.get(MarketplaceConnection, conn_id)
    if not conn:
        raise HTTPException(404, "Connection not found")
    return conn
