"""
Supplier Portal API — authenticated with supplier JWT.
Token payload: {"sub": str(supplier_id), "role": "supplier"}
"""
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone

from app.core.config import settings
from app.core.database import get_db
from app.core.security import verify_password, create_access_token, decode_token
from app.models.supplier import Supplier, Invoice
from app.models.product import Product, ProductSupplier
from app.models.order import Order, OrderLineItem, ShippingLabel, FulfillStatus
from app.api.v1.orders import _recalculate_order_status
from app.api.v1.easypost import ParcelIn, RateOut, RatesResponse
from app.integrations.easypost.client import (
    EasyPostClient, EasyPostError,
    supplier_to_ep_address, shipping_addr_to_ep, filter_usps_rates,
)
from app.schemas.order import ShippingLabelOut

router = APIRouter(prefix="/portal", tags=["supplier-portal"])


# --- Auth ---

@router.post("/login")
async def supplier_login(
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    username = body.get("username", "")
    password = body.get("password", "")
    result = await db.execute(select(Supplier).where(Supplier.username == username))
    supplier = result.scalar_one_or_none()
    if not supplier or not supplier.hashed_password:
        raise HTTPException(401, "Invalid credentials")
    if not verify_password(password, supplier.hashed_password):
        raise HTTPException(401, "Invalid credentials")
    token = create_access_token(supplier.id, extra={"role": "supplier"})
    return {
        "access_token": token,
        "token_type": "bearer",
        "supplier_id": supplier.id,
        "name": supplier.name,
        "can_buy_labels": supplier.can_buy_labels,
    }


async def get_current_supplier(
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
) -> Supplier:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Invalid auth header")
    token = authorization.split(" ", 1)[1]
    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(401, "Invalid token")
    if payload.get("role") != "supplier":
        raise HTTPException(403, "Supplier access only")
    supplier = await db.get(Supplier, int(payload["sub"]))
    if not supplier:
        raise HTTPException(404, "Supplier not found")
    return supplier


@router.get("/me")
async def portal_me(supplier: Supplier = Depends(get_current_supplier)):
    return {
        "id": supplier.id,
        "name": supplier.name,
        "email": supplier.email,
        "can_buy_labels": supplier.can_buy_labels,
    }


# --- Products ---

@router.get("/products")
async def portal_products(
    supplier: Supplier = Depends(get_current_supplier),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ProductSupplier).where(ProductSupplier.supplier_id == supplier.id)
    )
    ps_list = result.scalars().all()
    out = []
    for ps in ps_list:
        product = await db.get(Product, ps.product_id)
        if not product or not product.is_active:
            continue
        out.append({
            "product_supplier_id": ps.id,
            "product_id": product.id,
            "name": product.name,
            "sku": ps.supplier_sku or product.sku,
            "cost": float(ps.cost),
            "stock": ps.stock,
            "mockup_url": product.image_url,
            "lead_time_days": ps.lead_time_days,
        })
    return out


# --- Orders to fulfill ---

@router.get("/orders")
async def portal_orders(
    status: str | None = None,
    supplier: Supplier = Depends(get_current_supplier),
    db: AsyncSession = Depends(get_db),
):
    q = select(OrderLineItem).where(OrderLineItem.supplier_id == supplier.id)
    if status:
        q = q.where(OrderLineItem.fulfill_status == status)
    result = await db.execute(q.order_by(OrderLineItem.id.desc()))
    items = result.scalars().all()
    out = []
    for item in items:
        order = await db.get(Order, item.order_id)
        label = await db.get(ShippingLabel, item.label_id) if item.label_id else None
        out.append({
            "line_item_id": item.id,
            "order_id": item.order_id,
            "external_order_id": order.external_order_id if order else None,
            "marketplace": order.marketplace if order else None,
            "ordered_at": order.ordered_at.isoformat() if order else None,
            "buyer_name": order.buyer_name if order else None,
            "shipping_address": order.shipping_address if order else None,
            "product_name": item.product_name,
            "sku": item.sku,
            "quantity": item.quantity,
            "fulfill_status": item.fulfill_status,
            "tracking_number": item.tracking_number,
            "label_url": label.label_url if label else None,
            "fulfilled_at": item.fulfilled_at.isoformat() if item.fulfilled_at else None,
        })
    return out


@router.patch("/orders/{item_id}/ship")
async def mark_shipped(
    item_id: int,
    body: dict,
    supplier: Supplier = Depends(get_current_supplier),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(OrderLineItem).where(
            OrderLineItem.id == item_id,
            OrderLineItem.supplier_id == supplier.id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Order item not found")
    item.fulfill_status = FulfillStatus.shipped
    item.tracking_number = body.get("tracking_number") or item.tracking_number
    item.fulfilled_at = datetime.now(timezone.utc)

    order = await db.get(Order, item.order_id)
    if order:
        await _recalculate_order_status(order, db)

    await db.commit()
    return {"status": "shipped", "tracking_number": item.tracking_number}


# --- EasyPost label purchase (supplier self-service) ---

class PortalRatesRequest(BaseModel):
    order_id: int
    parcel: ParcelIn


class PortalBuyRequest(BaseModel):
    order_id: int
    shipment_id: str
    rate_id: str


def _require_can_buy_labels(supplier: Supplier) -> None:
    if not supplier.can_buy_labels:
        raise HTTPException(
            403,
            "Label purchase is not enabled for your account. Please contact the platform admin.",
        )


async def _supplier_line_items_for_order(
    db: AsyncSession, order_id: int, supplier_id: int
) -> list[OrderLineItem]:
    res = await db.execute(
        select(OrderLineItem).where(
            OrderLineItem.order_id == order_id,
            OrderLineItem.supplier_id == supplier_id,
            OrderLineItem.fulfill_status.in_([FulfillStatus.unfulfilled, FulfillStatus.pending]),
        )
    )
    return list(res.scalars().all())


@router.post("/orders/easypost/rates", response_model=RatesResponse)
async def portal_easypost_rates(
    body: PortalRatesRequest,
    supplier: Supplier = Depends(get_current_supplier),
    db: AsyncSession = Depends(get_db),
):
    _require_can_buy_labels(supplier)
    if not settings.EASYPOST_API_KEY:
        raise HTTPException(503, "EasyPost API key not configured")

    order = await db.get(Order, body.order_id)
    if not order:
        raise HTTPException(404, "Order not found")

    items = await _supplier_line_items_for_order(db, body.order_id, supplier.id)
    if not items:
        raise HTTPException(404, "No unshipped items in this order belong to you")
    if not order.shipping_address:
        raise HTTPException(400, "Order has no shipping address")
    if not supplier.street1:
        raise HTTPException(400, "Your supplier address is incomplete — ask the admin to update it")

    ep = EasyPostClient(settings.EASYPOST_API_KEY)
    try:
        shipment = await ep.create_shipment(
            supplier_to_ep_address(supplier),
            shipping_addr_to_ep(order.shipping_address),
            {
                "weight": body.parcel.weight,
                "length": body.parcel.length,
                "width": body.parcel.width,
                "height": body.parcel.height,
            },
        )
    except EasyPostError as e:
        raise HTTPException(e.status, str(e))

    all_rates = shipment.get("rates", [])
    usps = filter_usps_rates(all_rates) or all_rates
    rates_out = sorted(
        [
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
            for r in usps
        ],
        key=lambda r: float(r.rate),
    )
    return RatesResponse(shipment_id=shipment["id"], rates=rates_out)


@router.post("/orders/easypost/buy", response_model=ShippingLabelOut, status_code=201)
async def portal_easypost_buy(
    body: PortalBuyRequest,
    supplier: Supplier = Depends(get_current_supplier),
    db: AsyncSession = Depends(get_db),
):
    _require_can_buy_labels(supplier)
    if not settings.EASYPOST_API_KEY:
        raise HTTPException(503, "EasyPost API key not configured")

    order = await db.get(Order, body.order_id)
    if not order:
        raise HTTPException(404, "Order not found")

    items = await _supplier_line_items_for_order(db, body.order_id, supplier.id)
    if not items:
        raise HTTPException(404, "No unshipped items in this order belong to you")

    ep = EasyPostClient(settings.EASYPOST_API_KEY)
    try:
        bought = await ep.buy_shipment(body.shipment_id, body.rate_id)
    except EasyPostError as e:
        raise HTTPException(e.status, str(e))

    tracking = bought.get("tracking_code") or bought.get("selected_rate", {}).get("tracking_code")
    label_url = (
        bought.get("postage_label", {}).get("label_url")
        or bought.get("postage_label", {}).get("label_pdf_url")
    )
    cost_str = bought.get("selected_rate", {}).get("rate", "0")

    label = ShippingLabel(
        supplier_id=supplier.id,
        carrier="USPS",
        service=bought.get("selected_rate", {}).get("service", ""),
        tracking_number=tracking,
        label_url=label_url,
        cost=Decimal(str(cost_str)),
        from_address=bought.get("from_address"),
        to_address=bought.get("to_address"),
    )
    db.add(label)
    await db.flush()

    for li in items:
        li.label_id = label.id
        li.tracking_number = tracking
        if li.fulfill_status == FulfillStatus.unfulfilled:
            li.fulfill_status = FulfillStatus.pending

    await _recalculate_order_status(order, db)
    await db.commit()
    await db.refresh(label)
    return label


# --- Invoices ---

@router.get("/invoices")
async def portal_invoices(
    supplier: Supplier = Depends(get_current_supplier),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Invoice).where(Invoice.supplier_id == supplier.id).order_by(Invoice.created_at.desc())
    )
    invoices = result.scalars().all()
    return [
        {
            "id": inv.id,
            "invoice_number": inv.invoice_number,
            "period_start": inv.period_start.isoformat(),
            "period_end": inv.period_end.isoformat(),
            "total_amount": float(inv.total_amount),
            "status": inv.status,
            "paid_at": inv.paid_at.isoformat() if inv.paid_at else None,
            "created_at": inv.created_at.isoformat(),
        }
        for inv in invoices
    ]
