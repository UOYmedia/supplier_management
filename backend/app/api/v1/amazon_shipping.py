"""
Amazon Merchant Fulfillment (MFN) shipping endpoints.

POST /orders/{order_id}/amazon/rates  — get eligible shipping services
POST /orders/{order_id}/amazon/buy    — buy label, save ShippingLabel
GET  /orders/{order_id}/labels/{label_id}/download — download PDF label (Amazon or EasyPost)
"""
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from decimal import Decimal
import base64

from app.core.database import get_db
from app.models.order import Order, OrderLineItem, ShippingLabel, FulfillStatus
from app.models.supplier import Supplier
from app.models.marketplace import MarketplaceConnection, MarketplaceType
from app.integrations.amazon.client import AmazonSPClient, AmazonAPIError
from app.integrations.amazon.shipping import AmazonMFNShipping
from app.api.v1.orders import _recalculate_order_status
from app.schemas.order import ShippingLabelOut

router = APIRouter(prefix="/orders", tags=["amazon-shipping"])


class AmazonParcel(BaseModel):
    weight: float   # oz
    length: float   # inches
    width: float    # inches
    height: float   # inches


class AmazonRatesRequest(BaseModel):
    supplier_id: int
    line_item_ids: list[int] = []
    parcel: AmazonParcel


class AmazonServiceOut(BaseModel):
    shipping_service_id: str
    shipping_service_offer_id: str
    name: str
    carrier: str
    rate: float
    currency: str
    earliest_delivery: str | None
    latest_delivery: str | None


class AmazonRatesResponse(BaseModel):
    amazon_order_id: str
    services: list[AmazonServiceOut]


class AmazonBuyRequest(BaseModel):
    supplier_id: int
    amazon_order_id: str
    shipping_service_id: str
    shipping_service_offer_id: str
    line_item_ids: list[int] = []
    parcel: AmazonParcel


def _get_amazon_client(conn: MarketplaceConnection) -> AmazonSPClient:
    creds = conn.credentials or {}
    return AmazonSPClient(
        client_id=creds.get("client_id", ""),
        client_secret=creds.get("client_secret", ""),
        refresh_token=creds.get("refresh_token", ""),
        marketplace_id=conn.marketplace_id or "ATVPDKIKX0DER",
    )


async def _get_amazon_conn(order: Order, db: AsyncSession) -> MarketplaceConnection:
    """Return the Amazon connection for an order, or raise 400 if not applicable."""
    if not order.connection_id:
        raise HTTPException(400, "Order has no marketplace connection — use EasyPost instead")
    conn = await db.get(MarketplaceConnection, order.connection_id)
    if not conn or conn.marketplace != MarketplaceType.amazon:
        raise HTTPException(400, "Order is not from an Amazon connection — use EasyPost instead")
    if not order.external_order_id:
        raise HTTPException(400, "Order has no Amazon Order ID")
    return conn


@router.post("/{order_id}/amazon/rates", response_model=AmazonRatesResponse)
async def get_amazon_rates(order_id: int, body: AmazonRatesRequest, db: AsyncSession = Depends(get_db)):
    """Get eligible Amazon shipping services for a merchant-fulfilled order."""
    order = await db.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Order not found")

    conn = await _get_amazon_conn(order, db)

    supplier = await db.get(Supplier, body.supplier_id)
    if not supplier:
        raise HTTPException(404, "Supplier not found")
    if not supplier.street1:
        raise HTTPException(400, "Supplier address incomplete — update supplier profile")

    # Build order items list (need OrderItemId from Amazon)
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

    order_items = []
    for li_id in li_ids:
        res = await db.execute(select(OrderLineItem).where(OrderLineItem.id == li_id))
        li = res.scalar_one_or_none()
        if li:
            order_items.append({
                "OrderItemId": li.external_line_item_id or str(li.id),
                "Quantity": li.quantity,
            })

    if not order_items:
        raise HTTPException(400, "No eligible line items found")

    parcel = {
        "weight": body.parcel.weight,
        "length": body.parcel.length,
        "width": body.parcel.width,
        "height": body.parcel.height,
    }

    client = _get_amazon_client(conn)
    mfn = AmazonMFNShipping(client)

    try:
        services = await mfn.get_eligible_services(
            amazon_order_id=order.external_order_id,
            order_items=order_items,
            supplier=supplier,
            parcel=parcel,
        )
    except AmazonAPIError as e:
        raise HTTPException(e.status, f"Amazon API: {e.message}")

    return AmazonRatesResponse(
        amazon_order_id=order.external_order_id,
        services=[AmazonServiceOut(**s) for s in services],
    )


@router.post("/{order_id}/amazon/buy", response_model=ShippingLabelOut, status_code=201)
async def buy_amazon_label(order_id: int, body: AmazonBuyRequest, db: AsyncSession = Depends(get_db)):
    """Purchase an Amazon MFN shipping label and save it."""
    order = await db.get(Order, order_id)
    if not order:
        raise HTTPException(404, "Order not found")

    conn = await _get_amazon_conn(order, db)

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

    order_items = []
    for li_id in li_ids:
        res = await db.execute(select(OrderLineItem).where(OrderLineItem.id == li_id))
        li = res.scalar_one_or_none()
        if li:
            order_items.append({
                "OrderItemId": li.external_line_item_id or str(li.id),
                "Quantity": li.quantity,
            })

    if not order_items:
        raise HTTPException(400, "No eligible line items found")

    parcel = {
        "weight": body.parcel.weight,
        "length": body.parcel.length,
        "width": body.parcel.width,
        "height": body.parcel.height,
    }

    client = _get_amazon_client(conn)
    mfn = AmazonMFNShipping(client)

    try:
        result = await mfn.buy_label(
            amazon_order_id=body.amazon_order_id,
            order_items=order_items,
            supplier=supplier,
            parcel=parcel,
            shipping_service_id=body.shipping_service_id,
            shipping_service_offer_id=body.shipping_service_offer_id,
        )
    except AmazonAPIError as e:
        raise HTTPException(e.status, f"Amazon API: {e.message}")

    label = ShippingLabel(
        supplier_id=body.supplier_id,
        carrier=result["carrier"],
        service=result["service"],
        tracking_number=result["tracking_number"],
        label_data=result.get("label_data"),   # base64 PDF
        cost=Decimal(str(result.get("rate", 0))),
        from_address={"name": supplier.name, "street1": supplier.street1, "city": supplier.city},
        to_address=order.shipping_address,
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
            li.tracking_number = result["tracking_number"]
            if li.fulfill_status == FulfillStatus.unfulfilled:
                li.fulfill_status = FulfillStatus.pending

    await _recalculate_order_status(order, db)
    await db.commit()
    await db.refresh(label)
    return label


@router.get("/{order_id}/labels/{label_id}/download")
async def download_label(order_id: int, label_id: int, db: AsyncSession = Depends(get_db)):
    """Download shipping label as PDF (works for both Amazon MFN and EasyPost labels)."""
    label = await db.get(ShippingLabel, label_id)
    if not label:
        raise HTTPException(404, "Label not found")

    def _pdf_response(pdf_bytes: bytes) -> Response:
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"inline; filename=label_{label_id}.pdf"},
        )

    # Prefer stamping fresh from the pristine carrier PDF (label_url). This is the
    # source of truth: it guarantees the product info (Qty + NAME + size/pot +
    # date for JOE) is on the label even for older labels whose stored
    # label_data was saved before the stamp existed — and it never double-stamps,
    # since label_url is always the clean carrier label.
    if label.label_url:
        import httpx
        from app.api.v1.orders import _stamp_carrier_for_label
        from app.integrations.pdf_labels import image_to_label_pdf
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as http:
                r = await http.get(label.label_url)
            if r.is_success and r.content:
                carrier = (r.content if r.content[:5] == b"%PDF-"
                           else image_to_label_pdf(r.content))
                try:
                    carrier = await _stamp_carrier_for_label(carrier, label, db)
                except Exception:
                    pass
                return _pdf_response(carrier)
        except Exception:
            pass  # fall through to stored label_data / redirect

    # No usable label_url — fall back to the stored label_data (stamped at buy
    # time, or a manually uploaded PDF).
    if label.label_data:
        try:
            return _pdf_response(base64.b64decode(label.label_data))
        except Exception:
            raise HTTPException(500, "Failed to decode label data")

    if label.label_url:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=label.label_url)

    raise HTTPException(404, "No label data available")
