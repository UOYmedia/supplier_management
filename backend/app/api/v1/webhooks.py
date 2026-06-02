"""
Inbound webhook receivers.

POST /webhooks/easypost           -- EasyPost tracker.updated events
POST /easypost/register-webhook   -- register our URL with EasyPost (admin util)
GET  /easypost/list-webhooks      -- list registered EasyPost webhooks
"""
import hashlib
import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.config import settings
from app.models.order import Order, OrderLineItem, ShippingLabel, FulfillStatus, OrderEvent
from app.integrations.easypost.client import EasyPostClient, EasyPostError
from app.api.v1.orders import _recalculate_order_status

router = APIRouter(tags=["webhooks"])

# EasyPost tracker status → our FulfillStatus
_TRACKER_STATUS_MAP = {
    "pre_transit":        FulfillStatus.pending,
    "in_transit":         FulfillStatus.shipped,
    "out_for_delivery":   FulfillStatus.shipped,
    "delivered":          FulfillStatus.delivered,
    "return_to_sender":   FulfillStatus.returned,
    "cancelled":          FulfillStatus.cancelled,
}


def _verify_signature(body: bytes, header: str | None) -> bool:
    """Verify EasyPost HMAC-SHA256 signature. Passes if no secret is configured."""
    if not settings.EASYPOST_WEBHOOK_SECRET:
        return True
    if not header:
        return False
    # Header value: "hmac-sha256-hex=<hex>"
    sig = header.split("=", 1)[-1]
    expected = hmac.new(
        settings.EASYPOST_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, sig)


async def _log(db: AsyncSession, order_id: int, event_type: str, message: str,
               level: str = "info", payload: dict | None = None) -> None:
    db.add(OrderEvent(
        order_id=order_id,
        event_type=event_type,
        level=level,
        message=message,
        payload=payload,
    ))


@router.post("/webhooks/easypost", status_code=200)
async def easypost_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_hmac_signature: str | None = Header(None),
):
    """Receive EasyPost tracker events and update line item fulfillment statuses."""
    body = await request.body()

    if not _verify_signature(body, x_hmac_signature):
        raise HTTPException(401, "Invalid webhook signature")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    description = payload.get("description", "")
    result = payload.get("result") or {}

    if description != "tracker.updated":
        return {"status": "ignored", "description": description}

    tracking_code: str | None = result.get("tracking_code")
    tracker_status: str | None = result.get("status")
    shipment_id: str | None = result.get("shipment_id")

    if not tracking_code:
        return {"status": "ignored", "reason": "no tracking_code"}

    # Locate the label by tracking number, fall back to shipment_id
    label_res = await db.execute(
        select(ShippingLabel).where(ShippingLabel.tracking_number == tracking_code)
    )
    label = label_res.scalar_one_or_none()
    if not label and shipment_id:
        label_res = await db.execute(
            select(ShippingLabel).where(ShippingLabel.shipment_id == shipment_id)
        )
        label = label_res.scalar_one_or_none()

    if not label:
        return {"status": "ignored", "reason": "label not found", "tracking_code": tracking_code}

    new_status = _TRACKER_STATUS_MAP.get(tracker_status or "")

    # Find all line items linked to this label
    li_res = await db.execute(
        select(OrderLineItem).where(OrderLineItem.label_id == label.id)
    )
    line_items = li_res.scalars().all()

    updated_order_ids: set[int] = set()
    for li in line_items:
        if new_status:
            # Never regress from delivered; always allow returned/cancelled
            if li.fulfill_status != FulfillStatus.delivered or new_status in (
                FulfillStatus.cancelled, FulfillStatus.returned
            ):
                li.fulfill_status = new_status
                if new_status == FulfillStatus.delivered and not li.fulfilled_at:
                    li.fulfilled_at = datetime.now(timezone.utc)
        updated_order_ids.add(li.order_id)

    for order_id in updated_order_ids:
        order = await db.get(Order, order_id)
        if order:
            await _recalculate_order_status(order, db)
            await _log(
                db, order_id, "easypost_tracker",
                f"Tracker {tracking_code} → {tracker_status}",
                level="info",
                payload={
                    "tracking_code": tracking_code,
                    "tracker_status": tracker_status,
                    "shipment_id": shipment_id,
                    "label_id": label.id,
                    "line_item_ids": [li.id for li in line_items if li.order_id == order_id],
                },
            )

    await db.commit()
    return {
        "status": "ok",
        "tracking_code": tracking_code,
        "tracker_status": tracker_status,
        "updated_orders": list(updated_order_ids),
    }


def _require_easypost() -> EasyPostClient:
    if not settings.EASYPOST_API_KEY:
        raise HTTPException(503, "EasyPost API key not configured")
    return EasyPostClient(settings.EASYPOST_API_KEY)


@router.post("/easypost/register-webhook")
async def register_easypost_webhook():
    """Register our webhook URL with EasyPost. Requires BACKEND_URL to be set."""
    if not settings.BACKEND_URL:
        raise HTTPException(400, "BACKEND_URL not configured in environment")
    ep = _require_easypost()
    url = f"{settings.BACKEND_URL.rstrip('/')}/api/v1/webhooks/easypost"
    try:
        result = await ep.create_webhook(url, settings.EASYPOST_WEBHOOK_SECRET)
    except EasyPostError as e:
        raise HTTPException(e.status, str(e))
    return {"webhook_id": result.get("id"), "url": result.get("url"), "mode": result.get("mode")}


@router.get("/easypost/list-webhooks")
async def list_easypost_webhooks():
    """List all EasyPost webhooks registered for this account."""
    ep = _require_easypost()
    try:
        hooks = await ep.list_webhooks()
    except EasyPostError as e:
        raise HTTPException(e.status, str(e))
    return {"webhooks": hooks}
