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
    OrderFulfillmentItemOut, OrderFulfillmentItemUpdate,
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

        # Auto-assign from preferred ProductSupplier if no supplier given
        if not supplier_id and li.product_id:
            ps_result = await db.execute(
                select(ProductSupplier)
                .where(ProductSupplier.product_id == li.product_id, ProductSupplier.is_preferred == True)
            )
            ps = ps_result.scalar_one_or_none()
            if ps:
                supplier_id = ps.supplier_id
                base_cost = ps.cost

        line_item = OrderLineItem(
            order_id=order.id,
            product_id=li.product_id,
            supplier_id=supplier_id,
            listing_id=li.listing_id,
            product_name=li.product_name,
            sku=li.sku,
            quantity=li.quantity,
            price=li.price,
            base_cost=base_cost,
        )
        db.add(line_item)
        await db.flush()  # need line_item.id for fulfillment items

        # Auto-expand ProductComponents into OrderFulfillmentItems
        if li.product_id:
            comp_result = await db.execute(
                select(ProductComponent).where(ProductComponent.product_id == li.product_id)
            )
            for comp in comp_result.scalars().all():
                db.add(OrderFulfillmentItem(
                    order_line_item_id=line_item.id,
                    supplier_product_id=comp.supplier_product_id,
                    quantity=comp.quantity * li.quantity,
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

    # Propagate explicit terminal status to child fulfillment items so the two
    # sides stay in sync. Skip for intermediate states (unfulfilled/pending)
    # which would otherwise undo legitimate per-item progress.
    if body.fulfill_status in (
        FulfillStatus.shipped, FulfillStatus.delivered,
        FulfillStatus.cancelled, FulfillStatus.returned,
    ):
        fi_result = await db.execute(
            select(OrderFulfillmentItem).where(OrderFulfillmentItem.order_line_item_id == li.id)
        )
        for fi in fi_result.scalars().all():
            fi.fulfill_status = body.fulfill_status
            if body.fulfill_status == FulfillStatus.shipped and not fi.fulfilled_at:
                fi.fulfilled_at = datetime.now(timezone.utc)
            if body.tracking_number and not fi.tracking_number:
                fi.tracking_number = body.tracking_number

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
    """Assign a supplier (and optionally a specific catalog item) to a line item.

    When supplier_product_id is supplied, the variant is mapped through to the
    SupplierProduct via ProductComponent. This:
      * remembers the mapping for future orders of the same variant
      * recreates OrderFulfillmentItems on THIS line item so supplier stock /
        invoicing is computed against the correct catalog row, with
        quantity = units × line_item.quantity
      * derives base_cost as unit_price × units when not explicitly provided
    """
    result = await db.execute(
        select(OrderLineItem).where(OrderLineItem.id == li_id, OrderLineItem.order_id == order_id)
    )
    li = result.scalar_one_or_none()
    if not li:
        raise HTTPException(404, "Line item not found")

    supplier = await db.get(Supplier, body.supplier_id)
    if not supplier:
        raise HTTPException(404, "Supplier not found")

    sp = None
    if body.supplier_product_id is not None:
        sp = await db.get(SupplierProduct, body.supplier_product_id)
        if not sp or sp.supplier_id != body.supplier_id:
            raise HTTPException(400, "Supplier product does not belong to this supplier")
        if body.units < 1:
            raise HTTPException(400, "Units must be at least 1")

    li.supplier_id = body.supplier_id
    if body.base_cost is not None:
        li.base_cost = body.base_cost
    elif sp is not None:
        li.base_cost = sp.unit_price * body.units

    # Persist the variant ↔ supplier mapping at the product level
    if li.product_id and body.create_product_supplier:
        ps_result = await db.execute(
            select(ProductSupplier).where(
                ProductSupplier.product_id == li.product_id,
                ProductSupplier.supplier_id == body.supplier_id,
            )
        )
        ps = ps_result.scalar_one_or_none()
        cost_for_ps = body.base_cost if body.base_cost is not None else li.base_cost
        if not ps:
            ps = ProductSupplier(
                product_id=li.product_id,
                supplier_id=body.supplier_id,
                supplier_sku=sp.sku if sp else None,
                cost=cost_for_ps,
                is_preferred=body.is_preferred,
            )
            db.add(ps)
        else:
            if sp and not ps.supplier_sku:
                ps.supplier_sku = sp.sku
            ps.cost = cost_for_ps
            if body.is_preferred:
                all_ps = await db.execute(
                    select(ProductSupplier).where(ProductSupplier.product_id == li.product_id)
                )
                for other in all_ps.scalars().all():
                    other.is_preferred = False
                ps.is_preferred = True

    # Persist the variant ↔ catalog mapping and refresh this LI's fulfillment items
    if sp is not None and li.product_id:
        comp_q = await db.execute(
            select(ProductComponent).where(
                ProductComponent.product_id == li.product_id,
                ProductComponent.supplier_product_id == sp.id,
            )
        )
        comp = comp_q.scalar_one_or_none()
        if comp:
            comp.quantity = body.units
        else:
            db.add(ProductComponent(
                product_id=li.product_id,
                supplier_product_id=sp.id,
                quantity=body.units,
            ))

        # Replace any existing fulfillment items that no longer reflect the
        # mapping. Only safe to do when no fulfillment has progressed yet.
        existing_fi_q = await db.execute(
            select(OrderFulfillmentItem).where(
                OrderFulfillmentItem.order_line_item_id == li.id,
            )
        )
        existing_fis = existing_fi_q.scalars().all()
        all_safe = all(
            fi.fulfill_status in (FulfillStatus.unfulfilled,) and not fi.tracking_number
            for fi in existing_fis
        )
        if all_safe:
            for fi in existing_fis:
                await db.delete(fi)
            comps_q = await db.execute(
                select(ProductComponent).where(ProductComponent.product_id == li.product_id)
            )
            for c in comps_q.scalars().all():
                db.add(OrderFulfillmentItem(
                    order_line_item_id=li.id,
                    supplier_product_id=c.supplier_product_id,
                    quantity=c.quantity * li.quantity,
                ))

    order = await _get_or_404(order_id, db)
    await _recalculate_order_status(order, db)
    await db.commit()
    await db.refresh(li)
    return await _line_item_out(li, db)


# --- Fulfillment items ---

@router.get("/{order_id}/line-items/{li_id}/fulfillments", response_model=list[OrderFulfillmentItemOut])
async def list_fulfillment_items(order_id: int, li_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(OrderFulfillmentItem).where(OrderFulfillmentItem.order_line_item_id == li_id)
    )
    items = result.scalars().all()
    return [await _fulfillment_item_out(fi, db) for fi in items]


@router.patch("/{order_id}/line-items/{li_id}/fulfillments/{fi_id}", response_model=OrderFulfillmentItemOut)
async def update_fulfillment_item(
    order_id: int, li_id: int, fi_id: int,
    body: OrderFulfillmentItemUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(OrderFulfillmentItem).where(
            OrderFulfillmentItem.id == fi_id,
            OrderFulfillmentItem.order_line_item_id == li_id,
        )
    )
    fi = result.scalar_one_or_none()
    if not fi:
        raise HTTPException(404, "Fulfillment item not found")

    for k, v in body.model_dump(exclude_none=True).items():
        setattr(fi, k, v)
    if body.fulfill_status == FulfillStatus.shipped and not fi.fulfilled_at:
        fi.fulfilled_at = datetime.now(timezone.utc)

    # Roll up: FI → LI → Order
    li = await db.get(OrderLineItem, li_id)
    if li:
        await _recalculate_line_item_status(li, db)
    order = await _get_or_404(order_id, db)
    await _recalculate_order_status(order, db)
    await db.commit()
    await db.refresh(fi)

    # Auto-push tracking to marketplace after commit (best-effort)
    if body.fulfill_status == FulfillStatus.shipped and fi.tracking_number:
        await _push_tracking_to_marketplace(fi, order, db)

    return await _fulfillment_item_out(fi, db)


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


@router.get("/{order_id}/parcel-estimate")
async def estimate_parcel(
    order_id: int,
    supplier_id: int | None = Query(None),
    line_item_ids: str | None = Query(None, description="Comma-separated line item IDs"),
    db: AsyncSession = Depends(get_db),
):
    """Estimate parcel weight (oz) and dimensions (in) by summing per-unit
    SupplierProduct shipping data across the selected line items.

    Weight: Σ (unit weight × fulfillment qty) across all FIs of all LIs.
    Length / Width: max of any unit's dimension (items lay side-by-side).
    Height: Σ of (unit height × fulfillment qty) (items stacked vertically).
    Falls back to Product dimensions (kg/cm → oz/in) when no SupplierProduct
    weight/dimensions are set.
    """
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
            # No fulfillment items — fall back to shop product dimensions
            product = await db.get(Product, li.product_id) if li.product_id else None
            if not product or product.weight is None:
                missing.append({
                    "line_item_id": li.id,
                    "product_name": li.product_name,
                    "reason": "no_component_or_product_dims",
                })
                continue
            qty = li.quantity
            # Product stores kg/cm; convert
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

async def _recalculate_line_item_status(li: OrderLineItem, db: AsyncSession):
    """Roll up the line item's fulfill_status from its fulfillment items.

    Only applies to line items that actually have fulfillment items (i.e. the
    product had ProductComponents). Line items without fulfillment items keep
    their manually-set status.
    """
    fi_result = await db.execute(
        select(OrderFulfillmentItem).where(OrderFulfillmentItem.order_line_item_id == li.id)
    )
    fis = fi_result.scalars().all()
    if not fis:
        return

    statuses = [fi.fulfill_status for fi in fis]
    active = [s for s in statuses if s != FulfillStatus.cancelled]

    if not active:
        new_status = FulfillStatus.cancelled
    elif all(s == FulfillStatus.delivered for s in active):
        new_status = FulfillStatus.delivered
    elif all(s in (FulfillStatus.shipped, FulfillStatus.delivered) for s in active):
        new_status = FulfillStatus.shipped
    elif any(s in (FulfillStatus.pending, FulfillStatus.shipped, FulfillStatus.delivered) for s in active):
        new_status = FulfillStatus.pending
    else:
        new_status = FulfillStatus.unfulfilled

    li.fulfill_status = new_status
    if new_status == FulfillStatus.shipped and not li.fulfilled_at:
        li.fulfilled_at = datetime.now(timezone.utc)


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


async def _fulfillment_item_out(fi: OrderFulfillmentItem, db: AsyncSession) -> OrderFulfillmentItemOut:
    sp = await db.get(SupplierProduct, fi.supplier_product_id)
    sup = await db.get(Supplier, sp.supplier_id) if sp else None
    data = {c.name: getattr(fi, c.name) for c in fi.__table__.columns}
    data["supplier_product_name"] = sp.name if sp else None
    data["supplier_product_sku"] = sp.sku if sp else None
    data["supplier_id"] = sp.supplier_id if sp else None
    data["supplier_name"] = sup.name if sup else None
    return OrderFulfillmentItemOut(**data)


async def _line_item_out(li: OrderLineItem, db: AsyncSession) -> OrderLineItemOut:
    sup = await db.get(Supplier, li.supplier_id) if li.supplier_id else None
    fi_result = await db.execute(
        select(OrderFulfillmentItem).where(OrderFulfillmentItem.order_line_item_id == li.id)
    )
    fulfillment_items = [await _fulfillment_item_out(fi, db) for fi in fi_result.scalars().all()]
    data = {c.name: getattr(li, c.name) for c in li.__table__.columns}
    data["supplier_name"] = sup.name if sup else None
    data["fulfillment_items"] = fulfillment_items
    return OrderLineItemOut(**data)


async def _push_tracking_to_marketplace(fi: OrderFulfillmentItem, order: Order, db: AsyncSession) -> None:
    """Push tracking number to AMZ/Shopify after a fulfillment item is marked shipped."""
    try:
        li = await db.get(OrderLineItem, fi.order_line_item_id)
        if not li or not li.external_line_item_id or not fi.tracking_number:
            return
        if not order.connection_id or not order.external_order_id:
            return

        from app.models.marketplace import MarketplaceConnection
        conn = await db.get(MarketplaceConnection, order.connection_id)
        if not conn:
            return

        creds = conn.credentials or {}
        sp = await db.get(SupplierProduct, fi.supplier_product_id)
        carrier = "Other"
        if li.label_id:
            label = await db.get(ShippingLabel, li.label_id)
            if label:
                carrier = label.carrier or "Other"

        if order.marketplace == "amazon":
            from app.integrations.amazon.client import AmazonSPClient
            from app.integrations.amazon.fulfillment import AmazonFulfillment
            client = AmazonSPClient(
                client_id=creds.get("client_id", ""),
                client_secret=creds.get("client_secret", ""),
                refresh_token=creds.get("refresh_token", ""),
                marketplace_id=conn.marketplace_id or "ATVPDKIKX0DER",
                sandbox=creds.get("sandbox", False),
            )
            await AmazonFulfillment(client).confirm_shipment(
                amazon_order_id=order.external_order_id,
                order_item_id=li.external_line_item_id,
                quantity=li.quantity,
                tracking_number=fi.tracking_number,
                carrier_code=carrier,
            )

        elif order.marketplace == "shopify":
            from app.integrations.shopify.client import ShopifyClient
            from app.integrations.shopify.fulfillment import ShopifyFulfillment
            client = ShopifyClient(
                shop_url=conn.shop_url or creds.get("shop_url", ""),
                access_token=creds.get("access_token", ""),
            )
            sup = await db.get(Supplier, li.supplier_id) if li.supplier_id else None
            location_id = int(sup.shopify_location_id) if sup and sup.shopify_location_id else None
            await ShopifyFulfillment(client).create_fulfillment(
                shopify_order_id=order.external_order_id,
                line_item_id=li.external_line_item_id,
                tracking_number=fi.tracking_number,
                carrier=carrier,
                location_id=location_id,
            )
    except Exception as e:
        print(f"WARNING: push tracking to marketplace failed: {e}", flush=True)


async def _order_out(order: Order, db: AsyncSession) -> OrderOut:
    li_result = await db.execute(select(OrderLineItem).where(OrderLineItem.order_id == order.id))
    li_list = li_result.scalars().all()
    line_items = [await _line_item_out(li, db) for li in li_list]
    data = {c.name: getattr(order, c.name) for c in order.__table__.columns}
    data["line_items"] = line_items
    return OrderOut(**data)
