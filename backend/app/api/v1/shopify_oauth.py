"""
Shopify OAuth 2.0 — per-connection Partner App credentials

Flow:
  1. Frontend saves connection with client_id + client_secret via PATCH/POST
  2. Frontend calls GET /shopify/auth?connection_id=<id>  → JSON {"oauth_url": "..."}
  3. Frontend does window.location.href = oauth_url  → Shopify consent page
  4. User approves → Shopify redirects to BACKEND_URL/api/v1/shopify/callback
  5. Backend exchanges code → stores access_token in connection.credentials
  6. Backend redirects browser to FRONTEND_URL/marketplace?connected=shopify&id=<id>
"""

import hashlib
import hmac as hmac_lib
import secrets
from urllib.parse import quote as _urlencode

import httpx

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

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

# state token → connection_id  (in-memory; survives until backend restarts)
_pending: dict[str, int] = {}


def _callback_url() -> str:
    return settings.BACKEND_URL.rstrip("/") + "/api/v1/shopify/callback"


# ---------------------------------------------------------------------------
# Step 1 — return OAuth URL (frontend navigates there)
# ---------------------------------------------------------------------------

@router.get("/auth")
async def shopify_auth(
    connection_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    conn = await db.get(MarketplaceConnection, connection_id)
    if not conn or conn.marketplace != MarketplaceType.shopify:
        return JSONResponse({"error": "Shopify connection not found"}, status_code=404)

    creds = conn.credentials or {}
    client_id = creds.get("client_id") or settings.SHOPIFY_API_KEY
    if not client_id:
        return JSONResponse(
            {"error": "No Client ID configured. Add it in the connection settings."},
            status_code=400,
        )

    shop = (conn.shop_url or "").replace("https://", "").replace("http://", "").rstrip("/")
    if not shop:
        return JSONResponse({"error": "No shop URL configured on this connection"}, status_code=400)

    state = secrets.token_hex(16)
    _pending[state] = connection_id

    oauth_url = (
        f"https://{shop}/admin/oauth/authorize"
        f"?client_id={client_id}"
        f"&scope={SCOPES}"
        f"&redirect_uri={_callback_url()}"
        f"&state={state}"
    )
    return {"oauth_url": oauth_url}


# ---------------------------------------------------------------------------
# Step 2 — Shopify redirects back here after user approves
# ---------------------------------------------------------------------------

@router.get("/callback")
async def shopify_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    params = dict(request.query_params)
    shop = params.get("shop", "").strip()
    hmac_received = params.get("hmac", "")
    code = params.get("code", "")
    state = params.get("state", "")

    frontend = settings.FRONTEND_URL.rstrip("/")

    if not shop or not code:
        return RedirectResponse(f"{frontend}/marketplace?error={_urlencode('Missing shop or code')}")

    # Validate state
    connection_id = _pending.pop(state, None)
    if not connection_id:
        return RedirectResponse(f"{frontend}/marketplace?error={_urlencode('Invalid or expired OAuth state')}")

    conn = await db.get(MarketplaceConnection, connection_id)
    if not conn:
        return RedirectResponse(f"{frontend}/marketplace?error={_urlencode('Connection not found')}")

    creds = conn.credentials or {}
    client_id = creds.get("client_id") or settings.SHOPIFY_API_KEY
    client_secret = creds.get("client_secret") or settings.SHOPIFY_API_SECRET

    # HMAC verification
    if hmac_received and client_secret:
        verify_params = {k: v for k, v in params.items() if k != "hmac"}
        message = "&".join(f"{k}={v}" for k, v in sorted(verify_params.items()))
        digest = hmac_lib.new(client_secret.encode(), message.encode(), hashlib.sha256).hexdigest()
        if not hmac_lib.compare_digest(digest, hmac_received):
            return RedirectResponse(f"{frontend}/marketplace?error={_urlencode('HMAC verification failed')}")

    # Exchange code for offline access token
    access_token = None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"https://{shop}/admin/oauth/access_token",
                json={"client_id": client_id, "client_secret": client_secret, "code": code},
            )
            if resp.status_code == 200:
                access_token = resp.json().get("access_token")
    except Exception as e:
        return RedirectResponse(f"{frontend}/marketplace?error={_urlencode(str(e))}")

    if not access_token:
        return RedirectResponse(
            f"{frontend}/marketplace?error={_urlencode('Could not obtain access token from Shopify')}"
        )

    # Merge access_token into credentials (preserves client_id + client_secret)
    conn.credentials = {**creds, "access_token": access_token}
    conn.status = ConnectionStatus.active
    conn.error_message = None
    await db.commit()

    return RedirectResponse(f"{frontend}/marketplace?connected=shopify&id={conn.id}")
