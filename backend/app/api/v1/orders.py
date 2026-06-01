from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
from app.core.database import get_db
from app.models.order import Order, OrderLineItem, ShippingLabel, FulfillStatus, OrderStatus, OrderFulfillmentItem
from app.models.product import Product, ProductSupplier, ProductComponent
from app.models.supplier import Supplier, SupplierProduct
from app.schemas.order import (
    OrderCreate, OrderUpdate, OrderOut, OrderLineItemUpdate,
    OrderLineItemOut, ShippingLabelCreate, ShippingLabelOut, AssignSupplierBody,
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

    order = await _get_or_404(order_id, db)
    await _recalculate_order_status(order, db)
    await db.commit()
    await db.refresh(li)
    return await _line_item_out(li, db)


@router.patch("/{order_id}/line-items/{li_id}/assign-supplier", response_model=OrderLineItemOut)
async def assign_supplier_to_line_item(
    order_id: int,
    li_id: int,
    body: AssignSupplierBody,
    db: AsyncSession = Depends(get_db),
):
    """Assign a supplier to a line item. Optionally creates ProductSupplier for future auto-assignment."""
    result = await db.execute(
        select(OrderLineItem).where(OrderLineItem.id == li_id, OrderLineItem.order_id == order_id)
    )
    li = result.scalar_one_or_none()
    if not li:
        raise HTTPException(404, "Line item not found")

    supplier = await db.get(Supplier, body.supplier_id)
    if not supplier:
        raise HTTPException(404, "Supplier not found")

    li.supplier_id = body.supplier_id
    if body.base_cost is not None:
        li.base_cost = body.base_cost

    # Create ProductSupplier relationship for future auto-assignment
    if li.product_id and body.create_product_supplier:
        ps_result = await db.execute(
            select(ProductSupplier).where(
                ProductSupplier.product_id == li.product_id,
                ProductSupplier.supplier_id == body.supplier_id,
            )
        )
        ps = ps_result.scalar_one_or_none()
        if not ps:
            ps = ProductSupplier(
                product_id=li.product_id,
                supplier_id=body.supplier_id,
                cost=body.base_cost if body.base_cost is not None else li.base_cost,
                is_preferred=body.is_preferred,
            )
            db.add(ps)
        elif body.is_preferred:
            # If setting this as preferred, clear others
            all_ps = await db.execute(
                select(ProductSupplier).where(ProductSupplier.product_id == li.product_id)
            )
            for other in all_ps.scalars().all():
                other.is_preferred = False
            ps.is_preferred = True

    await db.commit()
    await db.refresh(li)
    return await _line_item_out(li, db)


# --- Shipping labels ---

@router.post("/{order_id}/labels", response_model=ShippingLabelOut, status_code=201)
async def create_label(order_id: int, body: ShippingLabelCreate, db: AsyncSession = Depends(get_db)):
    order = await _get_or_404(order_id, db)
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

    # Determine which line items to link:
    # Use explicitly provided IDs, or auto-select all unshipped items for this supplier
    li_ids = body.line_item_ids
    if not li_ids:
        auto_result = await db.execute(
            select(OrderLineItem).where(
                OrderLineItem.order_id == order_id,
                OrderLineItem.supplier_id == body.supplier_id,
                OrderLineItem.fulfill_status.in_([FulfillStatus.unfulfilled, FulfillStatus.pending]),
            )
        )
        li_ids = [li.id for li in auto_result.scalars().all()]

    for li_id in li_ids:
        result = await db.execute(
            select(OrderLineItem).where(OrderLineItem.id == li_id, OrderLineItem.order_id == order_id)
        )
        li = result.scalar_one_or_none()
        if li:
            li.label_id = label.id
            if body.tracking_number:
                li.tracking_number = body.tracking_number
            # Label bought → move to pending (awaiting shipment by supplier)
            if li.fulfill_status == FulfillStatus.unfulfilled:
                li.fulfill_status = FulfillStatus.pending

    await _recalculate_order_status(order, db)
    await db.commit()
    await db.refresh(label)
    return label


@router.get("/{order_id}/labels", response_model=list[ShippingLabelOut])
async def list_labels(order_id: int, db: AsyncSession = Depends(get_db)):
    await _get_or_404(order_id, db)
    label_ids_q = select(OrderLineItem.label_id).where(
        OrderLineItem.order_id == order_id,
        OrderLineItem.label_id.isnot(None),
    ).distinct()
    result = await db.execute(select(ShippingLabel).where(ShippingLabel.id.in_(label_ids_q)))
    return result.scalars().all()


@router.post("/{order_id}/labels/{label_id}/mark-printed")
async def mark_label_printed(order_id: int, label_id: int, db: AsyncSession = Depends(get_db)):
    label = await db.get(ShippingLabel, label_id)
    if not label:
        raise HTTPException(404, "Label not found")
    return {"status": "ok", "label_id": label_id}


@router.get("/{order_id}/parcel-estimate")
async def estimate_parcel(
    order_id: int,
    supplier_id: int | None = Query(None),
    line_item_ids: str | None = Query(None, description="Comma-separated line item IDs"),
    db: AsyncSession = Depends(get_db),
):
    """Estimate parcel weight (oz) and dimensions (in) from SupplierProduct shipping data."""
    await _get_or_404(order_id, db)

    li_q = select(OrderLineItem).where(OrderLineItem.order_id == order_id)
    if supplier_id is not None:
        li_q = li_q.where(OrderLineItem.supplier_id == supplier_id)
    if line_item_ids:
        try:
            ids = [int(x) for x in line_item_ids.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(400, "Invalid line_item_ids")
        li_q = li_q.where(OrderLineItem.id.in_(ids))
    li_res = await db.execute(li_q)
    lis = list(li_res.scalars().all())
    if not lis:
        raise HTTPException(404, "No matching line items")

    weight_oz = 0.0
    max_length_in = 0.0
    max_width_in = 0.0
    height_in_total = 0.0
    covered: list[int] = []
    missing: list[dict] = []

    KG_TO_OZ = 35.274
    CM_TO_IN = 0.393701

    for li in lis:
        fi_res = await db.execute(
            select(OrderFulfillmentItem).where(OrderFulfillmentItem.order_line_item_id == li.id)
        )
        fis = list(fi_res.scalars().all())

        if fis:
            for fi in fis:
                sp = await db.get(SupplierProduct, fi.supplier_product_id)
                if not sp:
                    missing.append({"line_item_id": li.id, "reason": "supplier_product_missing"})
                    continue
                qty = fi.quantity
                if sp.weight is None:
                    missing.append({
                        "line_item_id": li.id,
                        "supplier_product_id": sp.id,
                        "supplier_product_name": sp.name,
                        "reason": "no_weight",
                    })
                else:
                    weight_oz += float(sp.weight) * qty
                if sp.length is not None:
                    max_length_in = max(max_length_in, float(sp.length))
                if sp.width is not None:
                    max_width_in = max(max_width_in, float(sp.width))
                if sp.height is not None:
                    height_in_total += float(sp.height) * qty
                covered.append(li.id)
        else:
            product = await db.get(Product, li.product_id) if li.product_id else None
            if not product or product.weight is None:
                missing.append({
                    "line_item_id": li.id,
                    "product_name": li.product_name,
                    "reason": "no_component_or_product_dims",
                })
                continue
            qty = li.quantity
            weight_oz += float(product.weight) * KG_TO_OZ * qty
            if product.length is not None:
                max_length_in = max(max_length_in, float(product.length) * CM_TO_IN)
            if product.width is not None:
                max_width_in = max(max_width_in, float(product.width) * CM_TO_IN)
            if product.height is not None:
                height_in_total += float(product.height) * CM_TO_IN * qty
            covered.append(li.id)

    return {
        "weight": round(weight_oz, 2),
        "length": round(max_length_in, 2),
        "width": round(max_width_in, 2),
        "height": round(height_in_total, 2),
        "covered_line_item_ids": list(set(covered)),
        "missing": missing,
        "complete": len(missing) == 0 and weight_oz > 0,
    }


# --- Helpers ---

async def _recalculate_order_status(order: Order, db: AsyncSession):
    """Update order.status based on aggregate of line item fulfill_status values."""
    result = await db.execute(select(OrderLineItem).where(OrderLineItem.order_id == order.id))
    items = result.scalars().all()
    if not items:
        return

    statuses = [li.fulfill_status for li in items]
    active = [s for s in statuses if s != FulfillStatus.cancelled]

    if not active:
        order.status = OrderStatus.cancelled
    elif all(s in (FulfillStatus.shipped, FulfillStatus.delivered) for s in active):
        order.status = OrderStatus.fulfilled
    elif any(s in (FulfillStatus.shipped, FulfillStatus.delivered) for s in active):
        order.status = OrderStatus.partially_fulfilled
    elif any(s == FulfillStatus.pending for s in active):
        order.status = OrderStatus.processing
    else:
        order.status = OrderStatus.pending


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
