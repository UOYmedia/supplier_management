"""
EasyPost shipping endpoints.

POST /orders/{order_id}/easypost/rates   -- create shipment, return all carrier rates
POST /orders/{order_id}/easypost/buy     -- buy a rate, save ShippingLabel
POST /orders/{order_id}/easypost/refund  -- void a purchased label, cancel line items
GET  /orders/{order_id}/events           -- order event log (EasyPost debug history)
"""
import base64
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from decimal import Decimal, InvalidOperation

from app.core.database import get_db
from app.core.config import settings
from app.models.order import Order, OrderLineItem, ShippingLabel, FulfillStatus, OrderEvent
from app.models.supplier import Supplier
from app.integrations.easypost.client import (
    EasyPostClient, EasyPostError,
    supplier_to_ep_address, shipping_addr_to_ep,
)
from app.api.v1.orders import _recalculate_order_status, _line_item_out
from app.schemas.order import ShippingLabelOut

router = APIRouter(prefix="/orders", tags=["easypost"])


class ParcelIn(BaseModel):
    weight: float          # oz
    length: float          # inches
    width: float           # inches
    height: float          # inches


class RatesRequest(BaseModel):
    supplier_id: int
    line_item_ids: list[int] = []
    parcel: ParcelIn


class RateOut(BaseModel):
    id: str
    carrier: str
    service: str
    rate: str
    currency: str
    delivery_days: int | None
    delivery_date: str | None
    est_delivery_days: int | None


class DebugInfo(BaseModel):
    from_address: dict
    to_address: dict
    parcel: dict
    total_rates: int
    filtered_rates: int
    line_item_ids: list[int]


class RatesResponse(BaseModel):
    shipment_id: str
    rates: list[RateOut]
    debug: DebugInfo | None = None


class BuyRequest(BaseModel):
    supplier_id: int
    shipment_id: str
    rate_id: str
    line_item_ids: list[int] = []


class RefundRequest(BaseModel):
    label_id: int


class OrderEventOut(BaseModel):
    id: int
    event_type: str
    level: str
    message: str
    payload: dict | None
    created_at: datetime

    class Config:
        from_attributes = True


def _require_easypost() -> EasyPostClient:
    if not settings.EASYPOST_API_KEY:
        raise HTTPException(503, "EasyPost API key not configured")
    return EasyPostClient(settings.EASYPOST_API_KEY)


async def _log(db: AsyncSession, order_id: int, event_type: str, message: str,
               level: str = "info", payload: dict | None = None):
    ev = OrderEvent(
        order_id=order_id,
        event_type=event_type,
        level=level,
        message=message,
        payload=payload,
    )
    db.add(ev)


@router.get("/{order_id}/events", response_model=list[OrderEventOut])
async def list_order_events(order_id: int, db: AsyncSession = Depends(get_db)):
    """Return order event log (EasyPost requests, errors, status changes)."""
    result = await db.execute(
        select(OrderEvent)
        .where(OrderEvent.order_id == order_id)
        .order_by(OrderEvent.created_at.desc())
    )
    return result.scalars().all()


@router.post("/{order_id}/easypost/rates", response_model=RatesResponse)
async def get_rates(order_id: int, body: RatesRequest, db: AsyncSession = Depends(get_db)):
    """Create an EasyPost shipment and return available rates for all configured carriers."""
    ep = _require_easypost()

    order = await db.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Order not found")

    supplier = await db.get(Supplier, body.supplier_id)
    if not supplier:
        raise HTTPException(404, "Supplier not found")

    if not order.shipping_address:
        raise HTTPException(400, "Order has no shipping address")

    if not supplier.street1:
        raise HTTPException(400, "Supplier address is incomplete -- please update the supplier profile")

    from_addr = supplier_to_ep_address(supplier)
    to_addr = shipping_addr_to_ep(order.shipping_address)
    parcel = {
        "weight": body.parcel.weight,
        "length": body.parcel.length,
        "width": body.parcel.width,
        "height": body.parcel.height,
    }

    carrier_accounts = [
        x.strip() for x in settings.EASYPOST_CARRIER_ACCOUNT_IDS.split(",") if x.strip()
    ] or None

    try:
        shipment = await ep.create_shipment(to_addr, from_addr, parcel, carrier_accounts)
    except EasyPostError as e:
        await _log(db, order_id, "easypost_rates", str(e), level="error",
                   payload={"from": from_addr, "to": to_addr, "parcel": parcel, "http_status": e.status})
        await db.commit()
        raise HTTPException(e.status, str(e))
    except Exception as e:
        await _log(db, order_id, "easypost_rates", str(e), level="error",
                   payload={"from": from_addr, "to": to_addr, "parcel": parcel})
        await db.commit()
        raise HTTPException(500, f"Unexpected error: {e}")

    all_rates: list[dict] = shipment.get("rates", [])
    shown_rates = all_rates

    rates_out = [
        RateOut(
            id=r["id"],
            carrier=r.get("carrier", ""),
            service=r.get("service", ""),
            rate=r.get("rate", "0"),
            currency=r.get("currency", "USD"),
            delivery_days=r.get("delivery_days"),
            delivery_date=r.get("delivery_date"),
            est_delivery_days=r.get("est_delivery_days"),
        )
        for r in shown_rates
    ]
    rates_out.sort(key=lambda r: float(r.rate))

    await _log(db, order_id, "easypost_rates",
               f"Shipment {shipment['id']} created -- {len(rates_out)} rates returned",
               payload={
                   "shipment_id": shipment["id"],
                   "from": from_addr,
                   "to": to_addr,
                   "parcel": parcel,
                   "rate_count": len(rates_out),
               })
    await db.commit()

    debug = DebugInfo(
        from_address=from_addr,
        to_address=to_addr,
        parcel=parcel,
        total_rates=len(all_rates),
        filtered_rates=len(shown_rates),
        line_item_ids=body.line_item_ids,
    )
    return RatesResponse(shipment_id=shipment["id"], rates=rates_out, debug=debug)


@router.post("/{order_id}/easypost/buy", response_model=ShippingLabelOut, status_code=201)
async def buy_label(order_id: int, body: BuyRequest, db: AsyncSession = Depends(get_db)):
    """Purchase a rate and save the ShippingLabel. Idempotent: returns existing label if
    this shipment_id was already purchased (prevents double-charging on retry)."""
    ep = _require_easypost()

    try:
        order = await db.get(Order, order_id)
    except Exception as e:
        raise HTTPException(500, f"DB error loading order: {e}")
    if not order:
        raise HTTPException(404, "Order not found")

    try:
        supplier = await db.get(Supplier, body.supplier_id)
    except Exception as e:
        raise HTTPException(500, f"DB error loading supplier: {e}")
    if not supplier:
        raise HTTPException(404, "Supplier not found")

    # Idempotency: if this shipment was already purchased, return the existing label
    try:
        existing_label_res = await db.execute(
            select(ShippingLabel).where(ShippingLabel.shipment_id == body.shipment_id)
        )
        existing_label = existing_label_res.scalar_one_or_none()
    except Exception as e:
        raise HTTPException(500, f"DB error checking existing label: {e}")
    if existing_label:
        await _log(db, order_id, "easypost_buy",
                   f"Duplicate buy attempt for shipment {body.shipment_id} -- returning existing label {existing_label.id}",
                   level="warn", payload={"shipment_id": body.shipment_id, "label_id": existing_label.id})
        await db.commit()
        await db.refresh(existing_label)
        return existing_label

    # Determine which line items to attach
    li_ids = body.line_item_ids
    if not li_ids:
        try:
            auto = await db.execute(
                select(OrderLineItem).where(
                    OrderLineItem.order_id == order_id,
                    OrderLineItem.supplier_id == body.supplier_id,
                    OrderLineItem.fulfill_status.in_([FulfillStatus.unfulfilled, FulfillStatus.pending]),
                )
            )
            li_ids = [li.id for li in auto.scalars().all()]
        except Exception as e:
            raise HTTPException(500, f"DB error loading line items: {e}")

    # Guard: line items already have a different label
    if li_ids:
        try:
            already_labelled = await db.execute(
                select(OrderLineItem).where(
                    OrderLineItem.id.in_(li_ids),
                    OrderLineItem.label_id.isnot(None),
                )
            )
        except Exception as e:
            raise HTTPException(500, f"DB error checking label guard: {e}")
        if already_labelled.scalars().first():
            await _log(db, order_id, "easypost_buy",
                       "Buy blocked -- one or more line items already have a label",
                       level="warn", payload={"shipment_id": body.shipment_id, "li_ids": li_ids})
            await db.commit()
            raise HTTPException(422, "Label already exists for these items")

    if not body.shipment_id or not body.rate_id:
        raise HTTPException(400, "shipment_id and rate_id are required — refresh rates and try again")

    try:
        bought = await ep.buy_shipment(body.shipment_id, body.rate_id)
    except EasyPostError as e:
        msg = str(e)
        if "postage" in msg.lower() and "already" in msg.lower():
            # EasyPost already has a label for this shipment (bought outside our system
            # or in a previous attempt that didn't save to DB). Fetch the shipment so
            # we can save the label and return it instead of erroring.
            await _log(db, order_id, "easypost_buy",
                       f"EasyPost: postage already exists for {body.shipment_id} -- fetching existing shipment",
                       level="warn", payload={"shipment_id": body.shipment_id, "easypost_error": msg})
            try:
                bought = await ep.get_shipment(body.shipment_id)
            except Exception as fetch_err:
                await _log(db, order_id, "easypost_buy",
                           f"Failed to fetch existing shipment: {fetch_err}",
                           level="error", payload={"shipment_id": body.shipment_id})
                await db.commit()
                raise HTTPException(409, "Label already purchased for this shipment but could not retrieve it. Refresh rates to start fresh.")
        else:
            await _log(db, order_id, "easypost_buy", msg, level="error",
                       payload={"shipment_id": body.shipment_id, "rate_id": body.rate_id,
                                "http_status": e.status, "easypost_error": msg})
            await db.commit()
            raise HTTPException(e.status, msg)
    except Exception as e:
        await _log(db, order_id, "easypost_buy", str(e), level="error",
                   payload={"shipment_id": body.shipment_id, "rate_id": body.rate_id})
        await db.commit()
        raise HTTPException(500, f"Unexpected error: {e}")

    # Use `or {}` (not a get default): when recovering a shipment via get_shipment,
    # EasyPost can return these keys with an explicit null value, and .get(k, {})
    # only substitutes the default when the key is *absent*, not when it's null.
    selected_rate = bought.get("selected_rate") or {}
    postage_label = bought.get("postage_label") or {}
    tracking = bought.get("tracking_code") or selected_rate.get("tracking_code")
    label_url = postage_label.get("label_url") or postage_label.get("label_pdf_url")
    try:
        cost_str = selected_rate.get("rate") or "0"
        cost_val = Decimal(str(cost_str))
    except (InvalidOperation, ValueError):
        cost_val = Decimal("0")

    # Download PDF directly from label_url — shipments are created with label_format=PDF
    # so label_url should be a PDF. Skip PNG regeneration entirely to preserve quality.
    carrier_pdf_bytes: bytes | None = None
    carrier_png_b64: str | None = None
    if label_url:
        try:
            import httpx as _httpx
            async with _httpx.AsyncClient(timeout=20) as _http:
                _r = await _http.get(label_url)
            if _r.is_success:
                if _r.content[:5] == b"%PDF-":
                    carrier_pdf_bytes = _r.content
                elif _r.content[:8] == b'\x89PNG\r\n\x1a\n':
                    carrier_png_b64 = base64.b64encode(_r.content).decode()
                await _log(db, order_id, "easypost_buy",
                           f"Label download: {'PDF' if carrier_pdf_bytes else 'PNG' if carrier_png_b64 else 'unknown'} from {label_url[:60]}",
                           level="info", payload={"shipment_id": body.shipment_id})
        except Exception as _dl_err:
            await _log(db, order_id, "easypost_buy",
                       f"Label download failed: {_dl_err}",
                       level="warn", payload={"shipment_id": body.shipment_id})

    # label_data not needed — frontend uses label_url directly for display.
    # label_url is stored on the ShippingLabel record below.
    label_data = None

    try:
        label = ShippingLabel(
            supplier_id=body.supplier_id,
            carrier=selected_rate.get("carrier", "USPS"),
            service=selected_rate.get("service", ""),
            tracking_number=tracking,
            shipment_id=bought.get("id") or body.shipment_id,
            label_url=label_url,
            label_data=label_data,
            cost=cost_val,
            from_address=bought.get("from_address"),
            to_address=bought.get("to_address"),
        )
        db.add(label)
        await db.flush()

        for li_id in li_ids:
            res = await db.execute(
                select(OrderLineItem).where(OrderLineItem.id == li_id, OrderLineItem.order_id == order_id)
            )
            li = res.scalar_one_or_none()
            if li:
                li.label_id = label.id
                li.tracking_number = tracking
                if li.fulfill_status == FulfillStatus.unfulfilled:
                    li.fulfill_status = FulfillStatus.pending

        await _recalculate_order_status(order, db)

        await _log(db, order_id, "easypost_buy",
                   f"Label purchased -- tracking {tracking}, carrier {selected_rate.get('carrier')}, cost ${cost_val}",
                   payload={
                       "shipment_id": body.shipment_id,
                       "label_id": label.id,
                       "tracking_number": tracking,
                       "carrier": selected_rate.get("carrier"),
                       "service": selected_rate.get("service"),
                       "cost": str(cost_val),
                       "line_item_ids": li_ids,
                   })

        await db.commit()
        await db.refresh(label)
        return label
    except Exception as e:
        await db.rollback()
        raise HTTPException(500, f"DB error saving label: {e}")


@router.post("/{order_id}/easypost/refund", response_model=ShippingLabelOut)
async def refund_label(order_id: int, body: RefundRequest, db: AsyncSession = Depends(get_db)):
    """Void a purchased EasyPost label and cancel its associated line items.

    Submits a refund request to EasyPost, marks the label as refunded, detaches
    it from all line items, and recalculates the order status.
    """
    ep = _require_easypost()

    order = await db.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Order not found")

    label = await db.get(ShippingLabel, body.label_id)
    if not label:
        raise HTTPException(404, "Shipping label not found")

    if not label.shipment_id:
        raise HTTPException(422, "This label has no EasyPost shipment ID and cannot be refunded")

    if label.refunded_at is not None:
        raise HTTPException(409, "This label has already been refunded")

    # Guard: block refund if any line items are already shipped/delivered
    shipped_check = await db.execute(
        select(OrderLineItem).where(
            OrderLineItem.order_id == order_id,
            OrderLineItem.label_id == label.id,
            OrderLineItem.fulfill_status.in_([FulfillStatus.shipped, FulfillStatus.delivered]),
        )
    )
    if shipped_check.scalars().first():
        raise HTTPException(
            422,
            "Cannot cancel this label — one or more items have already been shipped or delivered",
        )

    try:
        refund = await ep.refund_shipment(label.shipment_id)
    except EasyPostError as e:
        await _log(db, order_id, "easypost_refund", str(e), level="error",
                   payload={"label_id": label.id, "shipment_id": label.shipment_id,
                            "http_status": e.status})
        await db.commit()
        raise HTTPException(e.status, str(e))
    except Exception as e:
        await _log(db, order_id, "easypost_refund", str(e), level="error",
                   payload={"label_id": label.id, "shipment_id": label.shipment_id})
        await db.commit()
        raise HTTPException(500, f"Unexpected error: {e}")

    # Fix: check EasyPost refund status before committing any DB changes
    refund_status = refund.get("status") if isinstance(refund, dict) else None
    if refund_status == "rejected":
        await _log(db, order_id, "easypost_refund",
                   f"EasyPost rejected refund for label {label.id} — no changes made",
                   level="error",
                   payload={"label_id": label.id, "shipment_id": label.shipment_id,
                            "refund_response": refund})
        await db.commit()
        raise HTTPException(422, "EasyPost rejected the refund request")

    label.refunded_at = datetime.now(timezone.utc)
    label.label_data = None
    label.label_url = None

    li_result = await db.execute(
        select(OrderLineItem).where(
            OrderLineItem.order_id == order_id,
            OrderLineItem.label_id == label.id,
        )
    )
    line_items = li_result.scalars().all()
    for li in line_items:
        li.label_id = None
        li.fulfill_status = FulfillStatus.cancelled

    await _recalculate_order_status(order, db)

    await _log(db, order_id, "easypost_refund",
               f"Label {label.id} (shipment {label.shipment_id}) refund {refund_status} — "
               f"{len(line_items)} line item(s) cancelled, label data cleared",
               payload={
                   "label_id": label.id,
                   "shipment_id": label.shipment_id,
                   "refund_status": refund_status,
                   "cancelled_line_item_ids": [li.id for li in line_items],
               })

    await db.commit()
    await db.refresh(label)
    return label
