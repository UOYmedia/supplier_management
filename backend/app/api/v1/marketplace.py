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


def _mask(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:3]}…{value[-3:]} (len {len(value)})"


@router.post("/connections/{conn_id}/debug")
async def debug_connection(conn_id: int, db: AsyncSession = Depends(get_db)):
    """Run a detailed diagnostic against the marketplace API and return every
    step's outcome so missing/wrong credentials show up clearly. Credentials
    are masked — only first/last 3 chars + length are returned.

    Never raises — every failure is captured into the report so the frontend
    always has something to show.
    """
    import httpx
    import traceback
    conn = await _get_conn_or_404(conn_id, db)
    creds = conn.credentials or {}

    def _enum_value(v):
        return v.value if hasattr(v, "value") else v

    report: dict = {
        "connection": {
            "id": conn.id,
            "name": conn.name,
            "marketplace": _enum_value(conn.marketplace),
            "marketplace_id": conn.marketplace_id,
            "status": _enum_value(conn.status),
            "last_synced_at": conn.last_synced_at.isoformat() if conn.last_synced_at else None,
            "error_message": conn.error_message,
            "shop_url": conn.shop_url,
        },
        "credentials_present": {
            "client_id": bool(creds.get("client_id")),
            "client_secret": bool(creds.get("client_secret")),
            "refresh_token": bool(creds.get("refresh_token")),
            "access_token": bool(creds.get("access_token")),
        },
        "credentials_masked": {
            "client_id": _mask(creds.get("client_id")),
            "client_secret": _mask(creds.get("client_secret")),
            "refresh_token": _mask(creds.get("refresh_token")),
            "access_token": _mask(creds.get("access_token")),
        },
        "checks": [],
    }

    def add(step: str, ok: bool, **extra):
        report["checks"].append({"step": step, "ok": ok, **extra})

    marketplace = _enum_value(conn.marketplace)

    try:
        if marketplace == "amazon":
            missing = [k for k in ("client_id", "client_secret", "refresh_token") if not creds.get(k)]
            if missing:
                add("credentials", False, missing=missing,
                    hint="Set Amazon LWA credentials on the connection.")
                return report
            add("credentials", True)

            from app.integrations.amazon.client import AmazonSPClient
            client = AmazonSPClient(
                client_id=creds["client_id"],
                client_secret=creds["client_secret"],
                refresh_token=creds["refresh_token"],
                marketplace_id=conn.marketplace_id or "ATVPDKIKX0DER",
            )
            try:
                async with httpx.AsyncClient(timeout=15) as http:
                    r = await http.post(client.LWA_TOKEN_URL, data={
                        "grant_type": "refresh_token",
                        "refresh_token": client.refresh_token,
                        "client_id": client.client_id,
                        "client_secret": client.client_secret,
                    })
                try:
                    body = r.json()
                except Exception:
                    body = {"text": r.text[:500]}
                ok = r.is_success
                add("lwa_token_exchange", ok, status=r.status_code,
                    response_keys=list(body.keys()) if isinstance(body, dict) else None,
                    error=(body.get("error") or body.get("error_description")) if (not ok and isinstance(body, dict)) else None,
                    expires_in=body.get("expires_in") if (ok and isinstance(body, dict)) else None,
                    token_type=body.get("token_type") if (ok and isinstance(body, dict)) else None,
                    hint=None if ok else "Check that the refresh_token is current and matches the LWA app's client_id/secret.",
                )
                if not ok:
                    return report
            except Exception as e:
                add("lwa_token_exchange", False, error=f"{type(e).__name__}: {e}")
                return report

            try:
                data = await client.get("/sellers/v1/marketplaceParticipations")
                payload = data.get("payload", [])
                marketplaces = []
                for p in payload if isinstance(payload, list) else []:
                    mp = p.get("marketplace") or {}
                    marketplaces.append({
                        "id": mp.get("id"),
                        "name": mp.get("name"),
                        "country_code": mp.get("countryCode"),
                        "default_currency_code": mp.get("defaultCurrencyCode"),
                        "is_participating": (p.get("participation") or {}).get("isParticipating"),
                    })
                add("sp_api_participations", True,
                    base_url=client.SP_API_BASE,
                    participation_count=len(marketplaces),
                    marketplaces=marketplaces,
                    configured_marketplace_id=client.marketplace_id,
                    configured_marketplace_in_list=any(m["id"] == client.marketplace_id for m in marketplaces),
                )
            except Exception as e:
                status = getattr(e, "status", None)
                add("sp_api_participations", False, status=status,
                    error=f"{type(e).__name__}: {str(e)[:500]}",
                    hint="Check IAM role, SP-API app roles (Sellers), and that the marketplace_id matches the LWA region.")

        elif marketplace == "shopify":
            from app.integrations.shopify.client import ShopifyClient
            if not creds.get("access_token"):
                add("credentials", False, missing=["access_token"])
                return report
            if not conn.shop_url:
                add("credentials", False, missing=["shop_url"])
                return report
            add("credentials", True)

            sclient = ShopifyClient(shop_url=conn.shop_url, access_token=creds["access_token"])
            try:
                data = await sclient.get("/shop.json")
                shop = data.get("shop", {}) if isinstance(data, dict) else {}
                add("shop_api", True,
                    shop_id=shop.get("id"),
                    shop_name=shop.get("name"),
                    domain=shop.get("domain"),
                    myshopify_domain=shop.get("myshopify_domain"),
                    country_code=shop.get("country_code"),
                    currency=shop.get("currency"),
                    plan_name=shop.get("plan_name"),
                )
            except Exception as e:
                add("shop_api", False, error=f"{type(e).__name__}: {str(e)[:500]}",
                    hint="Check access_token scope (read_orders / read_products) and shop_url.")

        else:
            add("marketplace_type", False, error=f"Unknown marketplace: {marketplace!r}")

    except Exception as e:
        # Anything unexpected — still return a usable report rather than 500.
        add("internal_error", False,
            error=f"{type(e).__name__}: {e}",
            traceback=traceback.format_exc()[-1500:],
            hint="Backend hit an unhandled exception while running diagnostics; check server logs.")

    return report


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


# --- Auto-map listings to products by SKU ---

@router.post("/listings/auto-map")
async def auto_map_listings(db: AsyncSession = Depends(get_db)):
    """Match unlinked listings to Products by marketplace_sku == Product.sku."""
    result = await db.execute(
        select(MarketplaceListing).where(MarketplaceListing.product_id.is_(None))
    )
    unlinked = result.scalars().all()
    mapped = 0
    unmatched = []
    for listing in unlinked:
        if not listing.marketplace_sku:
            unmatched.append(listing.title or str(listing.id))
            continue
        prod_res = await db.execute(
            select(Product).where(Product.sku == listing.marketplace_sku)
        )
        product = prod_res.scalar_one_or_none()
        if product:
            listing.product_id = product.id
            mapped += 1
        else:
            unmatched.append(listing.marketplace_sku)
    await db.commit()
    return {"mapped": mapped, "unmatched": unmatched}


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

@router.post("/connections/{conn_id}/sync-orders")
async def sync_orders(
    conn_id: int,
    background_tasks: BackgroundTasks,
    created_after: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Trigger order sync. Pass ?created_after=YYYY-MM-DDTHH:MM:SSZ to override
    the default 30-day window (Amazon SP-API requires this filter)."""
    conn = await _get_conn_or_404(conn_id, db)
    background_tasks.add_task(_do_sync_orders, conn_id, created_after)
    return {"message": "Order sync started in background"}


@router.post("/connections/{conn_id}/sync-products")
async def sync_products(conn_id: int, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    conn = await _get_conn_or_404(conn_id, db)
    background_tasks.add_task(_do_sync_products, conn_id)
    return {"message": "Product sync started in background"}


async def _do_sync_orders(conn_id: int, created_after: str | None = None):
    """Background task. Catches errors and records them on the connection so the
    user gets feedback instead of a silent no-op."""
    import traceback
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        conn = await db.get(MarketplaceConnection, conn_id)
        if not conn:
            return
        try:
            syncer = _get_syncer(conn)
            if isinstance(syncer, AmazonSync):
                await syncer.sync_orders(db, created_after=created_after)
            else:
                await syncer.sync_orders(db)
            conn.last_synced_at = datetime.now(timezone.utc)
            conn.error_message = None
            conn.status = ConnectionStatus.active
        except Exception as e:
            tb = traceback.format_exc()
            msg = f"{type(e).__name__}: {e}"
            print(f"sync_orders failed for conn={conn_id}: {msg}\n{tb}", flush=True)
            conn.error_message = msg[:500]
            conn.status = ConnectionStatus.error
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
