"""
Supplier Portal API — authenticated with supplier JWT.
Token payload: {"sub": str(supplier_id), "role": "supplier"}
"""
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone

from app.core.database import get_db
from app.core.security import verify_password, create_access_token, decode_token
from app.models.supplier import Supplier, Invoice
from app.models.product import Product, ProductSupplier
from app.models.order import Order, OrderLineItem, ShippingLabel, FulfillStatus
from app.api.v1.orders import _recalculate_order_status

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
    return {"access_token": token, "token_type": "bearer", "supplier_id": supplier.id, "name": supplier.name}


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
