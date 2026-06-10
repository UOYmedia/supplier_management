from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile, File
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


@router.get("/bulk-labels")
async def bulk_labels(
    date: str = Query(..., description="Date in YYYY-MM-DD format"),
    supplier_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Download purchased labels for a given date merged per supplier.
    supplier_id specified → single PDF. Omitted → zip of all suppliers."""
    import io as _io
    import zipfile
    import httpx
    from collections import defaultdict
    from app.integrations.pdf_labels import (
        decode_label_data, concat_label_pdfs,
        LabelEntry, PackItem, build_label_from_png,
    )

    try:
        d = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "Invalid date — use YYYY-MM-DD.")
    start = d.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
    end = d.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=timezone.utc)

    q = select(ShippingLabel).where(
        ShippingLabel.purchased_at >= start,
        ShippingLabel.purchased_at <= end,
    ).order_by(ShippingLabel.supplier_id)
    if supplier_id is not None:
        q = q.where(ShippingLabel.supplier_id == supplier_id)

    labels = (await db.execute(q)).scalars().all()
    if not labels:
        detail = f"No labels purchased on {date}"
        if supplier_id:
            detail += f" for supplier {supplier_id}"
        raise HTTPException(404, detail)

    date_label = start.strftime("%b").upper() + " " + str(start.day)

    async def _pdf_for_label(label: ShippingLabel) -> bytes | None:
        if label.label_data:
            return decode_label_data(label.label_data)
        if not label.label_url:
            return None
        try:
            async with httpx.AsyncClient(timeout=20) as http:
                r = await http.get(label.label_url)
            if not r.is_success:
                return None
            content = r.content
            if content[:5] == b"%PDF-":
                return content
            # PNG — rebuild with catalog overlay
            li_res = await db.execute(select(OrderLineItem).where(OrderLineItem.label_id == label.id))
            lis = li_res.scalars().all()
            pack_items: list[PackItem] = []
            for li in lis:
                pack_items.extend(await _catalog_items_for_line_item(li, db))
            order = await db.get(Order, lis[0].order_id) if lis else None
            sup = await db.get(Supplier, label.supplier_id)

            def _an(addr: dict | None) -> str | None:
                return (addr.get("name") or addr.get("Name")) if addr else None

            entry = LabelEntry(
                order_label=(order.external_order_id if order else f"Label #{label.id}"),
                ship_to=_an(order.shipping_address) if order else None,
                tracking_number=label.tracking_number,
                label_pdf=None,
                items=pack_items,
                supplier_name=sup.name if sup else None,
            )
            return build_label_from_png(content, entry)
        except Exception:
            return None

    async def _supplier_pdf(sup_labels: list) -> tuple[bytes | None, int]:
        label_ids = [lbl.id for lbl in sup_labels]
        oid_res = await db.execute(
            select(OrderLineItem.order_id)
            .where(OrderLineItem.label_id.in_(label_ids))
            .distinct()
        )
        n_orders = len(oid_res.scalars().all())
        pages = []
        for lbl in sup_labels:
            pdf = await _pdf_for_label(lbl)
            if pdf:
                pages.append(pdf)
        return (concat_label_pdfs(pages) if pages else None), n_orders

    by_sup: dict[int, list] = defaultdict(list)
    for lbl in labels:
        by_sup[lbl.supplier_id].append(lbl)

    if supplier_id is not None:
        sup = await db.get(Supplier, supplier_id)
        sup_name = (sup.name if sup else str(supplier_id)).upper()
        pdf, n_orders = await _supplier_pdf(list(by_sup.get(supplier_id, [])))
        if not pdf:
            raise HTTPException(404, "No printable label data found for this supplier/date")
        fname = f"{date_label} – {n_orders} ORDERS – {sup_name}.pdf"
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )

    zip_buf = _io.BytesIO()
    total = 0
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for sid, sup_labels in by_sup.items():
            sup = await db.get(Supplier, sid)
            sup_name = (sup.name if sup else str(sid)).upper()
            pdf, n_orders = await _supplier_pdf(sup_labels)
            if not pdf:
                continue
            fname = f"{date_label} – {n_orders} ORDERS – {sup_name}.pdf"
            zf.writestr(fname, pdf)
            total += 1
    if total == 0:
        raise HTTPException(404, "No printable label data found for any supplier on this date")
    zip_buf.seek(0)
    return Response(
        content=zip_buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{date_label} – labels.zip"'},
    )


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
    await _try_push_marketplace_tracking(order, db)
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
    if body.tracking_number:
        await _try_push_marketplace_tracking(order, db)
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
    """After the supplier prints the label we treat the items as shipped
    (label is committed at the carrier the moment it's purchased). Flip all
    line items + fulfillment items attached to this label, decrement supplier
    stock, then best-effort push tracking back to the marketplace (Shopify)."""
    label = await db.get(ShippingLabel, label_id)
    if not label:
        raise HTTPException(404, "Label not found")
    order = await _get_or_404(order_id, db)

    li_res = await db.execute(
        select(OrderLineItem).where(
            OrderLineItem.order_id == order_id,
            OrderLineItem.label_id == label_id,
        )
    )
    lis = list(li_res.scalars().all())
    now = datetime.now(timezone.utc)
    flipped = 0
    for li in lis:
        if li.fulfill_status not in (FulfillStatus.shipped, FulfillStatus.delivered):
            li.fulfill_status = FulfillStatus.shipped
            if not li.fulfilled_at:
                li.fulfilled_at = now
            flipped += 1
        if label.tracking_number and not li.tracking_number:
            li.tracking_number = label.tracking_number
        fi_res = await db.execute(
            select(OrderFulfillmentItem).where(OrderFulfillmentItem.order_line_item_id == li.id)
        )
        for fi in fi_res.scalars().all():
            if fi.fulfill_status not in (FulfillStatus.shipped, FulfillStatus.delivered):
                fi.fulfill_status = FulfillStatus.shipped
                if not fi.fulfilled_at:
                    fi.fulfilled_at = now
                sp_stock = await db.get(SupplierProduct, fi.supplier_product_id)
                if sp_stock:
                    sp_stock.stock_quantity = max(0, sp_stock.stock_quantity - fi.quantity)

    await _recalculate_order_status(order, db)
    await db.commit()
    await _try_push_marketplace_tracking(order, db)
    return {"status": "ok", "label_id": label_id, "marked_shipped": flipped}


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
    if "tracking_number" in data and data["tracking_number"]:
        await _try_push_marketplace_tracking(order, db)
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
    supplier = await db.get(Supplier, label.supplier_id) if label.supplier_id else None
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
            supplier_name=supplier.name if supplier else None,
        )
        combined_pdf = build_label_from_png(raw_png_bytes, entry)
    else:
        entry = LabelEntry(
            order_label=(order.external_order_id or f"Order #{order_id}"),
            ship_to=_addr_name(order.shipping_address),
            tracking_number=label.tracking_number,
            label_pdf=raw_pdf_bytes,
            items=pack_items,
            supplier_name=supplier.name if supplier else None,
        )
        combined_pdf = build_batch_label_pdf([entry])

    label.label_data = base64.b64encode(combined_pdf).decode()
    await db.commit()
    await db.refresh(label)
    return label


async def _push_shopify_tracking(order: Order, db: AsyncSession) -> dict:
    """Internal helper — push tracking back to Shopify via FulfillmentOrders API.
    Returns dict with synced/errors/tracking_number. Caller decides whether to
    raise HTTPException or just log."""
    if order.marketplace != "shopify":
        return {"skipped": "not a shopify order"}
    if not order.external_order_id:
        return {"skipped": "no external order id"}
    if not order.connection_id:
        return {"skipped": "no connection"}

    from app.models.marketplace import MarketplaceConnection
    conn = await db.get(MarketplaceConnection, order.connection_id)
    if not conn:
        return {"error": "connection not found"}
    creds = conn.credentials or {}
    access_token = creds.get("access_token")
    shop_url = conn.shop_url or creds.get("shop_url")
    if not access_token or not shop_url:
        return {"error": "shopify credentials incomplete"}

    li_res = await db.execute(
        select(OrderLineItem).where(
            OrderLineItem.order_id == order.id,
            OrderLineItem.label_id.isnot(None),
        )
    )
    lis = li_res.scalars().all()
    label_ids = list({li.label_id for li in lis if li.label_id})
    if not label_ids:
        return {"skipped": "no labels yet"}

    labels_map: dict[int, ShippingLabel] = {}
    for lid in label_ids:
        lbl = await db.get(ShippingLabel, lid)
        if lbl:
            labels_map[lid] = lbl
    tracking_label = next((l for l in labels_map.values() if l.tracking_number), None)
    if not tracking_label:
        return {"skipped": "no label has tracking yet"}

    from app.integrations.shopify.client import ShopifyClient
    client = ShopifyClient(shop_url, access_token)

    try:
        fulfillment_orders = await client.get_fulfillment_orders(order.external_order_id)
    except Exception as e:
        err_str = str(e)
        if "403" in err_str:
            return {"error": "Shopify connection needs re-authorization: the current token is missing fulfillment scopes (read_fulfillments / write_fulfillments). Go to Marketplace → your Shopify connection → Re-authorize to fix this."}
        return {"error": f"get_fulfillment_orders failed: {e}"}

    open_fos = [fo for fo in fulfillment_orders if fo.get("status") in ("open", "in_progress")]
    if not open_fos:
        return {"skipped": "no open fulfillment orders on Shopify (already fulfilled?)"}

    synced, errors = [], []
    for fo in open_fos:
        fo_id = fo["id"]
        try:
            result = await client.post("/fulfillments.json", {
                "fulfillment": {
                    "line_items_by_fulfillment_order": [{"fulfillment_order_id": fo_id}],
                    "tracking_info": {
                        "number": tracking_label.tracking_number,
                        "company": tracking_label.carrier or "USPS",
                    },
                    "notify_customer": True,
                }
            })
            synced.append({
                "fulfillment_order_id": fo_id,
                "fulfillment_id": result.get("fulfillment", {}).get("id"),
            })
        except Exception as e:
            errors.append({"fulfillment_order_id": fo_id, "error": str(e)[:300]})

    return {"synced": synced, "errors": errors, "tracking_number": tracking_label.tracking_number}


async def _try_push_marketplace_tracking(order: Order, db: AsyncSession) -> None:
    """Best-effort marketplace tracking sync, called after a line item flips to
    shipped. Never raises — just logs the outcome."""
    try:
        if order.marketplace == "shopify":
            result = await _push_shopify_tracking(order, db)
            if result.get("error"):
                print(f"Shopify tracking push order={order.id}: {result['error']}", flush=True)
            elif result.get("skipped"):
                print(f"Shopify tracking push order={order.id}: skipped — {result['skipped']}", flush=True)
            elif result.get("synced"):
                print(f"Shopify tracking push order={order.id}: synced {len(result['synced'])} fulfillment order(s), tracking={result.get('tracking_number')}", flush=True)
    except Exception as e:
        print(f"Marketplace tracking push order={order.id} crashed: {e}", flush=True)


@router.post("/{order_id}/sync-tracking")
async def sync_tracking_to_shopify(
    order_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Manual: push tracking to Shopify. Raises on hard error so the UI can show
    a meaningful message. Auto-sync after mark-shipped/print-label uses the
    silent helper."""
    order = await _get_or_404(order_id, db)
    if order.marketplace != "shopify":
        raise HTTPException(400, "Only Shopify orders support tracking sync")
    result = await _push_shopify_tracking(order, db)
    if result.get("error"):
        err = result["error"]
        status = 403 if "re-authorization" in err else 502
        raise HTTPException(status, err)
    if result.get("skipped"):
        raise HTTPException(400, result["skipped"])
    if not result.get("synced") and result.get("errors"):
        raise HTTPException(502, f"Shopify sync failed: {result['errors'][0]['error']}")
    return result


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
                items.append(PackItem(name=li.product_name or sp.short_name or sp.name, sku=sp.sku, quantity=fi.quantity))
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
                    items.append(PackItem(name=li.product_name or sp.short_name or sp.name, sku=sp.sku,
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
