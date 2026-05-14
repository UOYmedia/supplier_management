from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
from app.core.database import get_db
from app.models.order import Order, OrderLineItem, ShippingLabel
from app.models.product import Product, ProductSupplier
from app.models.supplier import Supplier
from app.schemas.order import (
    OrderCreate, OrderUpdate, OrderOut, OrderLineItemUpdate,
    OrderLineItemOut, ShippingLabelCreate, ShippingLabelOut
)

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("", response_model=list[OrderOut])
async def list_orders(
    marketplace: str | None = Query(None),
    status: str | None = Query(None),
    supplier_id: int | None = Query(None),
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    q = select(Order)
    if marketplace:
        q = q.where(Order.marketplace == marketplace)
    if status:
        q = q.where(Order.status == status)
    if supplier_id:
        q = q.where(Order.line_items.any(OrderLineItem.supplier_id == supplier_id))
    result = await db.execute(q.order_by(Order.ordered_at.desc()).offset(skip).limit(limit))
    orders = result.scalars().all()
    return [await _order_out(o, db) for o in orders]


@router.post("", response_model=OrderOut, status_code=201)
async def create_order(body: OrderCreate, db: AsyncSession = Depends(get_db)):
    order = Order(
        marketplace=body.marketplace,
        buyer_name=body.buyer_name,
        buyer_email=body.buyer_email,
        shipping_address=body.shipping_address.model_dump() if body.shipping_address else None,
        currency=body.currency,
        notes=body.notes,
        total=sum(li.price * li.quantity for li in body.line_items),
    )
    db.add(order)
    await db.flush()

    for li in body.line_items:
        supplier_id = li.supplier_id
        base_cost = li.base_cost
        # auto-assign preferred supplier if not provided
        if not supplier_id and li.product_id:
            ps_result = await db.execute(
                select(ProductSupplier)
                .where(ProductSupplier.product_id == li.product_id, ProductSupplier.is_preferred == True)
            )
            ps = ps_result.scalar_one_or_none()
            if ps:
                supplier_id = ps.supplier_id
                base_cost = ps.cost

        db.add(OrderLineItem(
            order_id=order.id,
            product_id=li.product_id,
            supplier_id=supplier_id,
            listing_id=li.listing_id,
            product_name=li.product_name,
            sku=li.sku,
            quantity=li.quantity,
            price=li.price,
            base_cost=base_cost,
        ))

    await db.commit()
    await db.refresh(order)
    return await _order_out(order, db)


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(order_id: int, db: AsyncSession = Depends(get_db)):
    order = await _get_or_404(order_id, db)
    return await _order_out(order, db)


@router.patch("/{order_id}", response_model=OrderOut)
async def update_order(order_id: int, body: OrderUpdate, db: AsyncSession = Depends(get_db)):
    order = await _get_or_404(order_id, db)
    data = body.model_dump(exclude_none=True)
    if "shipping_address" in data and data["shipping_address"]:
        data["shipping_address"] = data["shipping_address"].model_dump() if hasattr(data["shipping_address"], "model_dump") else data["shipping_address"]
    for k, v in data.items():
        setattr(order, k, v)
    await db.commit()
    await db.refresh(order)
    return await _order_out(order, db)


@router.delete("/{order_id}", status_code=204)
async def delete_order(order_id: int, db: AsyncSession = Depends(get_db)):
    order = await _get_or_404(order_id, db)
    await db.delete(order)
    await db.commit()


# --- Line items ---

@router.patch("/{order_id}/line-items/{li_id}", response_model=OrderLineItemOut)
async def update_line_item(order_id: int, li_id: int, body: OrderLineItemUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(OrderLineItem).where(OrderLineItem.id == li_id, OrderLineItem.order_id == order_id)
    )
    li = result.scalar_one_or_none()
    if not li:
        raise HTTPException(404, "Line item not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(li, k, v)
    if body.fulfill_status and body.fulfill_status == "shipped" and not li.fulfilled_at:
        li.fulfilled_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(li)
    return await _line_item_out(li, db)


# --- Shipping labels ---

@router.post("/{order_id}/labels", response_model=ShippingLabelOut, status_code=201)
async def create_label(order_id: int, body: ShippingLabelCreate, db: AsyncSession = Depends(get_db)):
    await _get_or_404(order_id, db)
    label = ShippingLabel(
        supplier_id=body.supplier_id,
        carrier=body.carrier,
        service=body.service,
        tracking_number=body.tracking_number,
        label_url=body.label_url,
        cost=body.cost,
        from_address=body.from_address,
        to_address=body.to_address,
    )
    db.add(label)
    await db.flush()

    # link line items to this label
    for li_id in body.line_item_ids:
        result = await db.execute(
            select(OrderLineItem).where(OrderLineItem.id == li_id, OrderLineItem.order_id == order_id)
        )
        li = result.scalar_one_or_none()
        if li:
            li.label_id = label.id
            if body.tracking_number:
                li.tracking_number = body.tracking_number

    await db.commit()
    await db.refresh(label)
    return label


@router.get("/{order_id}/labels", response_model=list[ShippingLabelOut])
async def list_labels(order_id: int, db: AsyncSession = Depends(get_db)):
    await _get_or_404(order_id, db)
    result = await db.execute(
        select(ShippingLabel).join(
            OrderLineItem, OrderLineItem.label_id == ShippingLabel.id
        ).where(OrderLineItem.order_id == order_id).distinct()
    )
    return result.scalars().all()


# --- Helpers ---

async def _get_or_404(order_id: int, db: AsyncSession) -> Order:
    o = await db.get(Order, order_id)
    if not o:
        raise HTTPException(404, "Order not found")
    return o


async def _line_item_out(li: OrderLineItem, db: AsyncSession) -> OrderLineItemOut:
    sup = await db.get(Supplier, li.supplier_id) if li.supplier_id else None
    data = {c.name: getattr(li, c.name) for c in li.__table__.columns}
    data["supplier_name"] = sup.name if sup else None
    return OrderLineItemOut(**data)


async def _order_out(order: Order, db: AsyncSession) -> OrderOut:
    li_result = await db.execute(select(OrderLineItem).where(OrderLineItem.order_id == order.id))
    li_list = li_result.scalars().all()
    line_items = [await _line_item_out(li, db) for li in li_list]
    data = {c.name: getattr(order, c.name) for c in order.__table__.columns}
    data["line_items"] = line_items
    return OrderOut(**data)
