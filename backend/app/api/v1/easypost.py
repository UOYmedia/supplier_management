"""
EasyPost shipping endpoints.

POST /orders/{order_id}/easypost/rates  — create shipment, return all carrier rates
POST /orders/{order_id}/easypost/buy    — buy a rate, save ShippingLabel
"""
import base64
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from decimal import Decimal

from app.core.database import get_db
from app.core.config import settings
from app.models.order import Order, OrderLineItem, ShippingLabel, FulfillStatus
from app.models.supplier import Supplier
from app.integrations.easypost.client import (
    EasyPostClient, EasyPostError,
    supplier_to_ep_address, shipping_addr_to_ep,
)
from app.api.v1.orders import _recalculate_order_status, _line_item_out, _catalog_items_for_line_item
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


def _require_easypost() -> EasyPostClient:
    if not settings.EASYPOST_API_KEY:
        raise HTTPException(503, "EasyPost API key not configured")
    return EasyPostClient(settings.EASYPOST_API_KEY)


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
        raise HTTPException(400, "Supplier address is incomplete — please update the supplier profile")

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
        raise HTTPException(e.status, str(e))
    except Exception as e:
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
    """Purchase a rate and save the ShippingLabel. Line items are moved to pending."""
    ep = _require_easypost()

    order = await db.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Order not found")

    supplier = await db.get(Supplier, body.supplier_id)
    if not supplier:
        raise HTTPException(404, "Supplier not found")

    li_ids = body.line_item_ids
    if not li_ids:
        auto = await db.execute(
            select(OrderLineItem).where(
                OrderLineItem.order_id == order_id,
                OrderLineItem.supplier_id == body.supplier_id,
                OrderLineItem.fulfill_status.in_([FulfillStatus.unfulfilled, FulfillStatus.pending]),
            )
        )
        li_ids = [li.id for li in auto.scalars().all()]

    if li_ids:
        existing = await db.execute(
            select(OrderLineItem).where(
                OrderLineItem.id.in_(li_ids),
                OrderLineItem.label_id.isnot(None),
            )
        )
        if existing.scalars().first():
            raise HTTPException(422, "Label already exists for these items")

    try:
        bought = await ep.buy_shipment(body.shipment_id, body.rate_id)
    except EasyPostError as e:
        msg = str(e)
        if "postage" in msg.lower() and "already" in msg.lower():
            raise HTTPException(409, "Label already purchased for this shipment. Please create new rates to buy a different label.")
        raise HTTPException(e.status, msg)

    selected_rate = bought.get("selected_rate", {})
    tracking = bought.get("tracking_code") or selected_rate.get("tracking_code")
    label_url = (
        bought.get("postage_label", {}).get("label_url")
        or bought.get("postage_label", {}).get("label_pdf_url")
    )
    cost_str = selected_rate.get("rate", "0")

    pack_items = []
    for li_id in li_ids:
        li_obj = await db.get(OrderLineItem, li_id)
        if li_obj:
            pack_items.extend(await _catalog_items_for_line_item(li_obj, db))

    carrier_png_b64 = await ep.fetch_label_pdf_b64(bought)

    def _ship_name(addr: dict | None) -> str | None:
        if not addr:
            return None
        return addr.get("name") or addr.get("Name") or addr.get("buyer_name")

    if carrier_png_b64 and pack_items:
        from app.integrations.pdf_labels import LabelEntry, build_label_from_png
        png_bytes = base64.b64decode(carrier_png_b64)
        entry = LabelEntry(
            order_label=(order.external_order_id or f"Order #{order_id}"),
            ship_to=_ship_name(order.shipping_address),
            tracking_number=tracking,
            label_pdf=None,
            items=pack_items,
        )
        label_data = base64.b64encode(build_label_from_png(png_bytes, entry)).decode()
    elif carrier_png_b64:
        from app.integrations.pdf_labels import image_to_label_pdf
        label_data = base64.b64encode(image_to_label_pdf(base64.b64decode(carrier_png_b64))).decode()
    else:
        label_data = None

    label = ShippingLabel(
        supplier_id=body.supplier_id,
        carrier=selected_rate.get("carrier", "USPS"),
        service=selected_rate.get("service", ""),
        tracking_number=tracking,
        shipment_id=bought.get("id") or body.shipment_id,
        label_url=label_url,
        label_data=label_data,
        cost=Decimal(str(cost_str)),
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
    await db.commit()
    await db.refresh(label)
    return label
