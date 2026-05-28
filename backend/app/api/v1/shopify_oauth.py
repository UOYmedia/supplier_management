"""
Shopify OAuth 2.0 — supports both flows:

  Standard (non-embedded):
    GET /api/v1/shopify/auth?shop=...  → Shopify consent → callback?code=...
    Callback exchanges code for offline access token.

  Embedded app (token exchange):
    Shopify sends callback?embedded=1&id_token=...&shop=...
    Callback exchanges id_token for offline access token.
"""

import hashlib
import hmac as hmac_lib
import secrets
from urllib.parse import quote as _urlencode
import httpx

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse, JSONResponse
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

_pending_nonces: set[str] = set()


def _callback_url() -> str:
    base = settings.BACKEND_URL.rstrip("/")
    return f"{base}/api/v1/shopify/callback"


# ---------------------------------------------------------------------------
# Step 1 – initiate OAuth
# ---------------------------------------------------------------------------

@router.get("/auth")
async def shopify_auth(
    shop: str = Query(..., description="e.g. gingerglow.myshopify.com"),
):
    shop = shop.strip().lower()
    if not shop.endswith(".myshopify.com"):
        return JSONResponse({"error": "shop must end with .myshopify.com"}, status_code=400)

    state = secrets.token_hex(16)
    _pending_nonces.add(state)

    url = (
        f"https://{shop}/admin/oauth/authorize"
        f"?client_id={settings.SHOPIFY_API_KEY}"
        f"&scope={SCOPES}"
        f"&redirect_uri={_callback_url()}"
        f"&state={state}"
    )
    return RedirectResponse(url)


# ---------------------------------------------------------------------------
# Step 2 – OAuth callback (standard code flow OR embedded id_token flow)
# ---------------------------------------------------------------------------

@router.get("/callback")
async def shopify_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    params = dict(request.query_params)
    shop = params.get("shop", "").strip()
    hmac_received = params.get("hmac", "")
    code = params.get("code")
    id_token = params.get("id_token")
    state = params.get("state")
    embedded = params.get("embedded") == "1"

    if not shop:
        return JSONResponse({"error": "Missing shop parameter"}, status_code=400)

    # --- HMAC verification (skip for embedded token-exchange flow) ---
    if not embedded and hmac_received:
        verify_params = {k: v for k, v in params.items() if k != "hmac"}
        message = "&".join(f"{k}={v}" for k, v in sorted(verify_params.items()))
        digest = hmac_lib.new(
            settings.SHOPIFY_API_SECRET.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac_lib.compare_digest(digest, hmac_received):
            return JSONResponse({"error": "HMAC verification failed"}, status_code=403)

    # --- State / nonce check (standard flow only) ---
    if state and not embedded:
        if state not in _pending_nonces:
            return JSONResponse({"error": "Invalid state/nonce"}, status_code=400)
        _pending_nonces.discard(state)

    # --- Exchange for access token ---
    access_token = None
    async with httpx.AsyncClient() as client:
        if code:
            # Standard OAuth code exchange
            resp = await client.post(
                f"https://{shop}/admin/oauth/access_token",
                json={
                    "client_id": settings.SHOPIFY_API_KEY,
                    "client_secret": settings.SHOPIFY_API_SECRET,
                    "code": code,
                },
            )
            if resp.status_code == 200:
                access_token = resp.json().get("access_token")

        elif id_token:
            # Embedded app token exchange (offline token)
            resp = await client.post(
                f"https://{shop}/admin/oauth/access_token",
                json={
                    "client_id": settings.SHOPIFY_API_KEY,
                    "client_secret": settings.SHOPIFY_API_SECRET,
                    "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                    "subject_token": id_token,
                    "subject_token_type": "urn:ietf:params:oauth:token-type:id_token",
                    "requested_token_type": "urn:shopify:params:oauth:token-type:offline-access-token",
                },
            )
            if resp.status_code == 200:
                access_token = resp.json().get("access_token")

    if not access_token:
        frontend = settings.FRONTEND_URL.rstrip("/")
        return RedirectResponse(
            f"{frontend}/marketplace?error={_urlencode('Could not obtain access token from Shopify')}"
        )

    # --- Upsert MarketplaceConnection ---
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

    frontend = settings.FRONTEND_URL.rstrip("/")
    return RedirectResponse(f"{frontend}/marketplace?connected=shopify&id={conn.id}")
