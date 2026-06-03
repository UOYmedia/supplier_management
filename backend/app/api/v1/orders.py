from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
import base64
from app.core.database import get_db
from app.models.order import Order, OrderLineItem, ShippingLabel, FulfillStatus, OrderStatus, OrderFulfillmentItem
from app.models.product import Product, ProductSupplier, ProductComponent
from app.models.supplier import Supplier, SupplierProduct
from app.schemas.order import (
    OrderCreate, OrderUpdate, OrderOut, OrderLineItemUpdate,
    OrderLineItemOut, ShippingLabelCreate, ShippingLabelOut, ShippingLabelUpdate,
    AssignSupplierBody, MarkShippedBody,
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


@router.post("/{order_id}/mark-shipped", response_model=OrderOut)
async def mark_shipped(order_id: int, body: MarkShippedBody, db: AsyncSession = Depends(get_db)):
    """Admin override: mark unshipped line items as shipped without buying a label.

    Use for orders already shipped outside the system. Targets the explicitly
    provided line_item_ids, or all unshipped items for a given supplier_id, or
    every unshipped item in the order when neither is supplied. Cascades the
    shipped status (and optional tracking number) to any fulfillment items.
    """
    order = await _get_or_404(order_id, db)

    q = select(OrderLineItem).where(
        OrderLineItem.order_id == order_id,
        OrderLineItem.fulfill_status.in_([FulfillStatus.unfulfilled, FulfillStatus.pending]),
    )
    if body.line_item_ids:
        q = q.where(OrderLineItem.id.in_(body.line_item_ids))
    elif body.supplier_id is not None:
        q = q.where(OrderLineItem.supplier_id == body.supplier_id)

    result = await db.execute(q)
    items = list(result.scalars().all())
    if not items:
        raise HTTPException(404, "No unshipped line items match this request")

    now = datetime.now(timezone.utc)
    for li in items:
        li.fulfill_status = FulfillStatus.shipped
        li.fulfilled_at = now
        if body.tracking_number:
            li.tracking_number = body.tracking_number

        fi_res = await db.execute(
            select(OrderFulfillmentItem).where(OrderFulfillmentItem.order_line_item_id == li.id)
        )
        for fi in fi_res.scalars().all():
            if fi.fulfill_status not in (FulfillStatus.shipped, FulfillStatus.delivered):
                fi.fulfill_status = FulfillStatus.shipped
                fi.fulfilled_at = now
                if body.tracking_number:
                    fi.tracking_number = body.tracking_number
                sp_stock = await db.get(SupplierProduct, fi.supplier_product_id)
                if sp_stock:
                    sp_stock.stock_quantity = max(0, sp_stock.stock_quantity - fi.quantity)

    await _recalculate_order_status(order, db)
    await db.commit()
    return await _order_out(order, db)


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

    # Validate supplier_product_id belongs to this supplier
    sp = await db.get(SupplierProduct, body.supplier_product_id)
    if not sp or sp.supplier_id != body.supplier_id:
        raise HTTPException(400, "Catalog item not found for this supplier")

    # Remove stale OFIs when re-assigning to a different catalog item
    old_fi_res = await db.execute(
        select(OrderFulfillmentItem).where(
            OrderFulfillmentItem.order_line_item_id == li.id,
            OrderFulfillmentItem.supplier_product_id != sp.id,
        )
    )
    for old_fi in old_fi_res.scalars().all():
        await db.delete(old_fi)

    li.supplier_id = body.supplier_id
    effective_cost = body.base_cost if body.base_cost is not None else (sp.unit_price * body.units)
    li.base_cost = effective_cost

    # If line item has no product_id, try to resolve it from SKU now so the
    # ProductComponent link can be stored for future orders with the same product.
    if not li.product_id and li.sku:
        from sqlalchemy import func as sqlfunc
        prod_res = await db.execute(
            select(Product).where(sqlfunc.lower(sqlfunc.trim(Product.sku)) == li.sku.strip().lower())
        )
        product = prod_res.scalar_one_or_none()
        if product:
            li.product_id = product.id

    # Upsert ProductComponent (product → supplier catalog item) — reusable for all
    # future orders that carry the same product_id.
    if li.product_id:
        comp_res = await db.execute(
            select(ProductComponent).where(
                ProductComponent.product_id == li.product_id,
                ProductComponent.supplier_product_id == sp.id,
            )
        )
        comp = comp_res.scalar_one_or_none()
        if not comp:
            db.add(ProductComponent(
                product_id=li.product_id,
                supplier_product_id=sp.id,
                quantity=body.units,
            ))
        else:
            comp.quantity = body.units

        # Create ProductSupplier relationship for future auto-assignment
        if body.create_product_supplier:
            ps_result = await db.execute(
                select(ProductSupplier).where(
                    ProductSupplier.product_id == li.product_id,
                    ProductSupplier.supplier_id == body.supplier_id,
                )
            )
            ps_link = ps_result.scalar_one_or_none()
            if not ps_link:
                ps_link = ProductSupplier(
                    product_id=li.product_id,
                    supplier_id=body.supplier_id,
                    cost=effective_cost,
                    is_preferred=body.is_preferred,
                )
                db.add(ps_link)
            elif body.is_preferred:
                all_ps = await db.execute(
                    select(ProductSupplier).where(ProductSupplier.product_id == li.product_id)
                )
                for other in all_ps.scalars().all():
                    other.is_preferred = False
                ps_link.is_preferred = True

    # Always create/upsert OrderFulfillmentItem for this specific line item,
    # whether or not product_id exists — this is what the supplier sees immediately.
    fi_res = await db.execute(
        select(OrderFulfillmentItem).where(
            OrderFulfillmentItem.order_line_item_id == li.id,
            OrderFulfillmentItem.supplier_product_id == sp.id,
        )
    )
    fi = fi_res.scalar_one_or_none()
    if not fi:
        db.add(OrderFulfillmentItem(
            order_line_item_id=li.id,
            supplier_product_id=sp.id,
            quantity=body.units * li.quantity,
        ))
    else:
        fi.quantity = body.units * li.quantity

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


@router.patch("/{order_id}/labels/{label_id}", response_model=ShippingLabelOut)
async def update_label(
    order_id: int, label_id: int, body: ShippingLabelUpdate, db: AsyncSession = Depends(get_db)
):
    """Edit an existing label (manual override / replay).

    Lets an admin fix the carrier/service/cost, swap in a new tracking number,
    or point label_url at a manually-provided label. The new tracking number
    cascades to every line item (and fulfillment item) linked to this label.
    """
    order = await _get_or_404(order_id, db)
    label = await db.get(ShippingLabel, label_id)
    if not label:
        raise HTTPException(404, "Label not found")

    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(label, k, v)

    # Cascade a changed tracking number to the linked line/fulfillment items
    if "tracking_number" in data:
        li_res = await db.execute(
            select(OrderLineItem).where(
                OrderLineItem.order_id == order_id,
                OrderLineItem.label_id == label_id,
            )
        )
        for li in li_res.scalars().all():
            li.tracking_number = data["tracking_number"]
        fi_res = await db.execute(
            select(OrderFulfillmentItem).where(OrderFulfillmentItem.label_id == label_id)
        )
        for fi in fi_res.scalars().all():
            fi.tracking_number = data["tracking_number"]

    await db.commit()
    await db.refresh(label)
    return label


@router.post("/{order_id}/labels/{label_id}/upload", response_model=ShippingLabelOut)
async def upload_label_pdf(
    order_id: int, label_id: int, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)
):
    """Attach a manually-provided PDF label to an existing label record.

    Useful when a label was bought outside the system, or when the archived
    PDF is missing and needs to be re-supplied (\"replay\"). The PDF is stored
    base64-encoded so it can be served same-origin for printing.
    """
    await _get_or_404(order_id, db)
    label = await db.get(ShippingLabel, label_id)
    if not label:
        raise HTTPException(404, "Label not found")

    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Uploaded file is empty")
    if raw[:5] != b"%PDF-":
        raise HTTPException(400, "Please upload a PDF file")

    label.label_data = base64.b64encode(raw).decode()
    await db.commit()
    await db.refresh(label)
    return label


@router.post("/{order_id}/labels/{label_id}/regenerate", response_model=ShippingLabelOut)
async def regenerate_label(
    order_id: int,
    label_id: int,
    size: str = Query("4x6", description="EasyPost label size, e.g. 4x6 or 7x3"),
    db: AsyncSession = Depends(get_db),
):
    """Regenerate the label PDF on demand (e.g. to repair a missing archive or
    change the printed size).

    Preferred path: re-request the label PNG from EasyPost and build a combined
    PDF with the catalog overlay strip. Fallback: re-fetch the stored label_url.
    """
    label = await db.get(ShippingLabel, label_id)
    if not label:
        raise HTTPException(404, "Label not found")

    from app.core.config import settings
    from app.integrations.pdf_labels import (
        LabelEntry, PackItem, build_label_from_png, build_batch_label_pdf, image_to_label_pdf,
    )

    raw_png_bytes: bytes | None = None
    raw_pdf_bytes: bytes | None = None

    # Preferred: regenerate PNG from EasyPost
    if label.shipment_id and settings.EASYPOST_API_KEY:
        from app.integrations.easypost.client import EasyPostClient, EasyPostError
        ep = EasyPostClient(settings.EASYPOST_API_KEY)
        try:
            png_b64, png_url = await ep.regenerate_label(label.shipment_id, size)
        except EasyPostError as e:
            raise HTTPException(e.status, str(e))
        if png_b64:
            raw_png_bytes = base64.b64decode(png_b64)
            if png_url:
                label.label_url = png_url

    # Fallback: re-fetch the stored label URL
    if raw_png_bytes is None and label.label_url:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as http:
                r = await http.get(label.label_url)
        except Exception as e:
            raise HTTPException(502, f"Could not fetch the stored label URL: {e}")
        if not r.is_success:
            raise HTTPException(502, f"Label URL returned HTTP {r.status_code} — it may have expired. Upload a PDF manually instead.")
        content = r.content
        if content[:5] == b"%PDF-":
            raw_pdf_bytes = content
        else:
            raw_png_bytes = content

    if raw_png_bytes is None and raw_pdf_bytes is None:
        raise HTTPException(400, "This label has no EasyPost shipment or stored URL to regenerate from — upload a PDF manually instead.")

    # Build pack items using catalog lookup
    order = await _get_or_404(order_id, db)
    lis_result = await db.execute(
        select(OrderLineItem).where(
            OrderLineItem.order_id == order_id,
            OrderLineItem.label_id == label_id,
        )
    )
    lis = lis_result.scalars().all()

    pack_items: list[PackItem] = []
    for li in lis:
        pack_items.extend(await _catalog_items_for_line_item(li, db))

    if not pack_items:
        all_lis_result = await db.execute(
            select(OrderLineItem).where(OrderLineItem.order_id == order_id)
        )
        for li in all_lis_result.scalars().all():
            pack_items.extend(await _catalog_items_for_line_item(li, db))

    def _addr_name(addr: dict | None) -> str | None:
        if not addr:
            return None
        return addr.get("name") or addr.get("Name") or addr.get("full_name") or addr.get("buyer_name")

    if raw_png_bytes:
        entry = LabelEntry(
            order_label=(order.external_order_id or f"Order #{order_id}"),
            ship_to=_addr_name(order.shipping_address),
            tracking_number=label.tracking_number,
            label_pdf=None,
            items=pack_items,
        )
        combined_pdf = build_label_from_png(raw_png_bytes, entry)
    else:
        entry = LabelEntry(
            order_label=(order.external_order_id or f"Order #{order_id}"),
            ship_to=_addr_name(order.shipping_address),
            tracking_number=label.tracking_number,
            label_pdf=raw_pdf_bytes,
            items=pack_items,
        )
        combined_pdf = build_batch_label_pdf([entry])

    label.label_data = base64.b64encode(combined_pdf).decode()
    await db.commit()
    await db.refresh(label)
    return label


@router.post("/{order_id}/sync-tracking")
async def sync_tracking_to_shopify(
    order_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Push tracking numbers for shipped/pending line items to Shopify.

    Uses the Fulfillment Orders API: fetches open fulfillment orders for the
    Shopify order, then creates a fulfillment with the tracking info from the
    first label found on the order's line items.
    """
    order = await _get_or_404(order_id, db)
    if order.marketplace != "shopify":
        raise HTTPException(400, "Only Shopify orders support tracking sync")
    if not order.external_order_id:
        raise HTTPException(400, "Order has no Shopify order ID")
    if not order.connection_id:
        raise HTTPException(400, "Order has no marketplace connection")

    from app.models.marketplace import MarketplaceConnection
    conn = await db.get(MarketplaceConnection, order.connection_id)
    if not conn:
        raise HTTPException(404, "Marketplace connection not found")
    creds = conn.credentials or {}
    access_token = creds.get("access_token")
    shop_url = conn.shop_url or creds.get("shop_url")
    if not access_token or not shop_url:
        raise HTTPException(400, "Shopify connection credentials are incomplete")

    # Collect labels linked to this order's line items
    li_res = await db.execute(
        select(OrderLineItem).where(
            OrderLineItem.order_id == order_id,
            OrderLineItem.label_id.isnot(None),
        )
    )
    lis = li_res.scalars().all()
    label_ids = list({li.label_id for li in lis if li.label_id})
    if not label_ids:
        raise HTTPException(400, "No labels found on this order — buy a label first")

    labels_map: dict[int, ShippingLabel] = {}
    for lid in label_ids:
        lbl = await db.get(ShippingLabel, lid)
        if lbl:
            labels_map[lid] = lbl

    # Pick the most relevant label (prefer one with tracking)
    tracking_label: ShippingLabel | None = next(
        (l for l in labels_map.values() if l.tracking_number), None
    )
    if not tracking_label:
        raise HTTPException(400, "No label with a tracking number found")

    tracking_number = tracking_label.tracking_number
    carrier = tracking_label.carrier or "USPS"

    from app.integrations.shopify.client import ShopifyClient
    client = ShopifyClient(shop_url, access_token)

    fulfillment_orders = await client.get_fulfillment_orders(order.external_order_id)
    open_fos = [fo for fo in fulfillment_orders if fo.get("status") in ("open", "in_progress")]
    if not open_fos:
        raise HTTPException(400, "No open fulfillment orders found on Shopify — order may already be fulfilled")

    synced = []
    errors = []
    for fo in open_fos:
        fo_id = fo["id"]
        try:
            result = await client.post(
                "/fulfillments.json",
                {
                    "fulfillment": {
                        "line_items_by_fulfillment_order": [
                            {"fulfillment_order_id": fo_id}
                        ],
                        "tracking_info": {
                            "number": tracking_number,
                            "company": carrier,
                        },
                        "notify_customer": True,
                    }
                },
            )
            synced.append({
                "fulfillment_order_id": fo_id,
                "fulfillment_id": result.get("fulfillment", {}).get("id"),
            })
        except Exception as e:
            errors.append({"fulfillment_order_id": fo_id, "error": str(e)})

    if not synced and errors:
        raise HTTPException(502, f"Shopify sync failed: {errors[0]['error']}")

    return {"synced": synced, "errors": errors, "tracking_number": tracking_number}


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


async def _catalog_items_for_line_item(li: OrderLineItem, db: AsyncSession) -> list:
    """Resolve catalog name+qty for a line item via OFI → ProductComponent → SupplierProduct."""
    from app.integrations.pdf_labels import PackItem
    # Prefer OFI (already resolved and persisted)
    fi_res = await db.execute(
        select(OrderFulfillmentItem).where(OrderFulfillmentItem.order_line_item_id == li.id)
    )
    fis = fi_res.scalars().all()
    if fis:
        items = []
        for fi in fis:
            sp = await db.get(SupplierProduct, fi.supplier_product_id)
            if sp:
                items.append(PackItem(name=sp.short_name or sp.name, sku=sp.sku, quantity=fi.quantity))
        if items:
            return items
    if li.product_id:
        comps = (await db.execute(
            select(ProductComponent).where(ProductComponent.product_id == li.product_id)
        )).scalars().all()
        if comps:
            items = []
            for comp in comps:
                sp = await db.get(SupplierProduct, comp.supplier_product_id)
                if sp:
                    items.append(PackItem(name=sp.short_name or sp.name, sku=sp.sku,
                                          quantity=li.quantity * comp.quantity))
            if items:
                return items
    return [PackItem(name=li.product_name, sku=li.sku, quantity=li.quantity)]


async def _line_item_out(li: OrderLineItem, db: AsyncSession) -> OrderLineItemOut:
    sup = await db.get(Supplier, li.supplier_id) if li.supplier_id else None
    data = {c.name: getattr(li, c.name) for c in li.__table__.columns}
    data["supplier_name"] = sup.name if sup else None

    mapping_suggestion = None
    if not li.supplier_id:
        from sqlalchemy import func as sqlfunc
        product_id = li.product_id
        if not product_id and li.sku:
            prod_res = await db.execute(
                select(Product).where(sqlfunc.lower(sqlfunc.trim(Product.sku)) == li.sku.strip().lower())
            )
            prod = prod_res.scalar_one_or_none()
            if prod:
                product_id = prod.id
        if product_id:
            comp_res = await db.execute(
                select(ProductComponent).where(ProductComponent.product_id == product_id)
            )
            comp = comp_res.scalars().first()
            if comp:
                sp = await db.get(SupplierProduct, comp.supplier_product_id)
                if sp:
                    sp_sup = await db.get(Supplier, sp.supplier_id)
                    mapping_suggestion = {
                        "supplier_id": sp.supplier_id,
                        "supplier_name": sp_sup.name if sp_sup else None,
                        "supplier_product_id": sp.id,
                        "catalog_name": sp.short_name or sp.name,
                        "catalog_sku": sp.sku,
                        "units": comp.quantity,
                    }
    data["mapping_suggestion"] = mapping_suggestion
    return OrderLineItemOut(**data)


async def _order_out(order: Order, db: AsyncSession) -> OrderOut:
    li_result = await db.execute(select(OrderLineItem).where(OrderLineItem.order_id == order.id))
    li_list = li_result.scalars().all()
    line_items = [await _line_item_out(li, db) for li in li_list]
    data = {c.name: getattr(order, c.name) for c in order.__table__.columns}
    data["line_items"] = line_items
    return OrderOut(**data)
