"""
Shopify OAuth 2.0 flow.

Install flow:
  1. Frontend (or direct browser) hits GET /api/v1/shopify/auth?shop=gingerglow.myshopify.com
  2. Backend redirects to Shopify's OAuth consent screen.
  3. Shopify redirects to GET /api/v1/shopify/callback?shop=...&code=...&hmac=...
  4. Backend verifies HMAC, exchanges code for access token, saves MarketplaceConnection.
  5. Redirects browser to frontend /marketplace page.
"""

import hashlib
import hmac as hmac_lib
import secrets
import httpx

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.database import get_db
from app.models.marketplace import MarketplaceConnection, MarketplaceType, ConnectionStatus

router = APIRouter(prefix="/shopify", tags=["shopify-oauth"])

SCOPES = (
    "read_products,write_products,"
    "read_orders,write_orders,"
    "read_inventory,write_inventory,"
    "read_fulfillments,write_fulfillments,"
    "read_shipping,write_shipping"
)

# In-memory nonce store (fine for single-instance; swap for Redis in multi-replica)
_pending_nonces: set[str] = set()


def _callback_url(request: Request) -> str:
    """Build the absolute callback URL from the incoming request."""
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/v1/shopify/callback"


@router.get("/auth")
async def shopify_auth(
    shop: str = Query(..., description="e.g. gingerglow.myshopify.com"),
    request: Request = None,
):
    """Step 1 — redirect user to Shopify consent screen."""
    shop = shop.strip().lower()
    if not shop.endswith(".myshopify.com"):
        raise HTTPException(400, "shop must end with .myshopify.com")

    state = secrets.token_hex(16)
    _pending_nonces.add(state)

    redirect_uri = _callback_url(request)
    url = (
        f"https://{shop}/admin/oauth/authorize"
        f"?client_id={settings.SHOPIFY_API_KEY}"
        f"&scope={SCOPES}"
        f"&redirect_uri={redirect_uri}"
        f"&state={state}"
    )
    return RedirectResponse(url)


@router.get("/callback")
async def shopify_callback(
    shop: str = Query(...),
    code: str = Query(...),
    hmac: str = Query(...),
    state: str = Query(...),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """Step 2 — verify HMAC, exchange code, save connection."""

    # --- 1. Verify state nonce ---
    if state not in _pending_nonces:
        raise HTTPException(400, "Invalid state/nonce")
    _pending_nonces.discard(state)

    # --- 2. Verify HMAC ---
    params = dict(request.query_params)
    params.pop("hmac", None)
    message = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    digest = hmac_lib.new(
        settings.SHOPIFY_API_SECRET.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac_lib.compare_digest(digest, hmac):
        raise HTTPException(403, "HMAC verification failed")

    # --- 3. Exchange code for access token ---
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://{shop}/admin/oauth/access_token",
            json={
                "client_id": settings.SHOPIFY_API_KEY,
                "client_secret": settings.SHOPIFY_API_SECRET,
                "code": code,
            },
        )
        if resp.status_code != 200:
            raise HTTPException(502, f"Token exchange failed: {resp.text}")
        token_data = resp.json()

    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(502, "No access_token in Shopify response")

    # --- 4. Upsert MarketplaceConnection ---
    shop_url = f"https://{shop}"
    result = await db.execute(
        select(MarketplaceConnection).where(
            MarketplaceConnection.shop_url == shop_url,
            MarketplaceConnection.marketplace == MarketplaceType.shopify,
        )
    )
    conn = result.scalar_one_or_none()

    if conn:
        conn.credentials = {"access_token": access_token}
        conn.status = ConnectionStatus.active
        conn.error_message = None
    else:
        shop_name = shop.replace(".myshopify.com", "").capitalize()
        conn = MarketplaceConnection(
            name=shop_name,
            marketplace=MarketplaceType.shopify,
            shop_url=shop_url,
            credentials={"access_token": access_token},
            status=ConnectionStatus.active,
        )
        db.add(conn)

    await db.commit()
    await db.refresh(conn)

    # --- 5. Redirect to frontend ---
    frontend = settings.FRONTEND_URL.rstrip("/")
    return RedirectResponse(f"{frontend}/marketplace?connected=shopify&id={conn.id}")
