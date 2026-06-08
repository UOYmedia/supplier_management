from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.models.supplier import Supplier, Invoice, InvoiceLineItem, SupplierProduct
from app.models.product import ProductSupplier, ProductComponent
from app.models.order import Order, OrderLineItem, OrderFulfillmentItem, FulfillStatus, ShippingLabel
from app.schemas.supplier import (
    SupplierCreate, SupplierUpdate, SupplierOut, SupplierListOut,
    InvoiceCreate, InvoiceUpdate, InvoiceOut,
    InvoicePreviewResponse, InvoicePreviewItem, InvoiceFromOrdersCreate,
)
from app.schemas.supplier_product import (
    SupplierProductCreate, SupplierProductUpdate, SupplierProductOut
)
import csv
import io
import uuid
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@router.get("", response_model=list[SupplierListOut])
async def list_suppliers(
    search: str | None = Query(None),
    is_active: bool | None = Query(None),
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    q = select(Supplier)
    if search:
        q = q.where(Supplier.name.ilike(f"%{search}%"))
    if is_active is not None:
        q = q.where(Supplier.is_active == is_active)
    result = await db.execute(q.offset(skip).limit(limit))
    suppliers = result.scalars().all()

    out = []
    for s in suppliers:
        ps_q = await db.execute(select(ProductSupplier).where(ProductSupplier.supplier_id == s.id))
        ps_list = ps_q.scalars().all()
        out.append(SupplierListOut(
            id=s.id, name=s.name, email=s.email, phone=s.phone,
            city=s.city, state=s.state, country=s.country, zipcode=s.zipcode,
            is_active=s.is_active,
            product_count=len(ps_list),
            total_stock=sum(ps.stock for ps in ps_list),
        ))
    return out


@router.post("", response_model=SupplierOut, status_code=201)
async def create_supplier(body: SupplierCreate, db: AsyncSession = Depends(get_db)):
    from app.core.security import hash_password
    data = body.model_dump(exclude={"password"})
    if body.password:
        data["hashed_password"] = hash_password(body.password)
    supplier = Supplier(**data)
    db.add(supplier)
    await db.commit()
    await db.refresh(supplier)
    return supplier


@router.get("/{supplier_id}", response_model=SupplierOut)
async def get_supplier(supplier_id: int, db: AsyncSession = Depends(get_db)):
    return await _get_or_404(supplier_id, db)


@router.patch("/{supplier_id}", response_model=SupplierOut)
async def update_supplier(supplier_id: int, body: SupplierUpdate, db: AsyncSession = Depends(get_db)):
    from app.core.security import hash_password
    supplier = await _get_or_404(supplier_id, db)
    data = body.model_dump(exclude_none=True, exclude={"password"})
    for k, v in data.items():
        setattr(supplier, k, v)
    if body.password:
        supplier.hashed_password = hash_password(body.password)
    await db.commit()
    await db.refresh(supplier)
    return supplier


@router.delete("/{supplier_id}", status_code=204)
async def delete_supplier(supplier_id: int, db: AsyncSession = Depends(get_db)):
    supplier = await _get_or_404(supplier_id, db)
    await db.delete(supplier)
    await db.commit()


# --- Supplier inventory (legacy ProductSupplier-based, kept for backward compat) ---

@router.get("/{supplier_id}/inventory")
async def supplier_inventory(supplier_id: int, db: AsyncSession = Depends(get_db)):
    await _get_or_404(supplier_id, db)
    result = await db.execute(
        select(ProductSupplier).where(ProductSupplier.supplier_id == supplier_id)
    )
    ps_list = result.scalars().all()
    return [
        {
            "product_supplier_id": ps.id,
            "product_id": ps.product_id,
            "supplier_sku": ps.supplier_sku,
            "cost": float(ps.cost),
            "stock": ps.stock,
            "lead_time_days": ps.lead_time_days,
        }
        for ps in ps_list
    ]


@router.patch("/{supplier_id}/inventory/{ps_id}")
async def update_stock(
    supplier_id: int, ps_id: int,
    stock: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ProductSupplier).where(
            ProductSupplier.id == ps_id,
            ProductSupplier.supplier_id == supplier_id
        )
    )
    ps = result.scalar_one_or_none()
    if not ps:
        raise HTTPException(404, "Not found")
    ps.stock = stock
    await db.commit()
    return {"stock": stock}


# --- Supplier product catalog ---

@router.get("/{supplier_id}/products", response_model=list[SupplierProductOut])
async def list_supplier_products(supplier_id: int, db: AsyncSession = Depends(get_db)):
    await _get_or_404(supplier_id, db)
    result = await db.execute(
        select(SupplierProduct).where(SupplierProduct.supplier_id == supplier_id)
    )
    products = result.scalars().all()
    return [await _supplier_product_out(sp, db) for sp in products]


@router.post("/{supplier_id}/products", response_model=SupplierProductOut, status_code=201)
async def create_supplier_product(
    supplier_id: int, body: SupplierProductCreate, db: AsyncSession = Depends(get_db)
):
    await _get_or_404(supplier_id, db)
    sp = SupplierProduct(supplier_id=supplier_id, **body.model_dump())
    db.add(sp)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(400, f"SKU '{body.sku}' already exists for this supplier")
    await db.refresh(sp)
    return await _supplier_product_out(sp, db)


CATALOG_CSV_COLUMNS = [
    "name", "sku", "unit_price", "stock_quantity",
    "weight", "length", "width", "height",
]


def _fmt_dim(v) -> str:
    return "" if v is None else f"{v}"


def _csv_bytes(rows: list[list]) -> bytes:
    """Build CSV bytes with UTF-8 BOM so Excel preserves encoding on save."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    for row in rows:
        writer.writerow(row)
    return "﻿".encode("utf-8") + buf.getvalue().encode("utf-8")


@router.get("/{supplier_id}/products/export.csv")
async def export_supplier_catalog(supplier_id: int, db: AsyncSession = Depends(get_db)):
    supplier = await _get_or_404(supplier_id, db)
    result = await db.execute(
        select(SupplierProduct).where(SupplierProduct.supplier_id == supplier_id)
    )
    products = result.scalars().all()

    rows = [CATALOG_CSV_COLUMNS] + [
        [sp.name, sp.sku, f"{sp.unit_price:.2f}", sp.stock_quantity,
         _fmt_dim(sp.weight), _fmt_dim(sp.length), _fmt_dim(sp.width), _fmt_dim(sp.height)]
        for sp in products
    ]
    safe_name = "".join(c if c.isalnum() else "_" for c in supplier.name)[:40] or "supplier"
    filename = f"{safe_name}_catalog_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    return Response(
        content=_csv_bytes(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{supplier_id}/products/template.csv")
async def supplier_catalog_template(supplier_id: int, db: AsyncSession = Depends(get_db)):
    await _get_or_404(supplier_id, db)
    rows = [
        CATALOG_CSV_COLUMNS,
        ["Example Product", "SKU-001", "9.99", "100", "8.5", "12", "9", "4"],
    ]
    return Response(
        content=_csv_bytes(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="catalog_template.csv"'},
    )


@router.post("/{supplier_id}/products/import/csv", status_code=201)
async def import_supplier_catalog(
    supplier_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    await _get_or_404(supplier_id, db)

    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Uploaded file is empty")

    # Detect common non-CSV formats
    if raw[:4] in (b"PK\x03\x04", b"PK\x05\x06") or raw[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise HTTPException(400, "Please upload a CSV file, not an Excel file (.xlsx / .xls). "
                            "In Excel: File -> Save As -> CSV (Comma delimited).")

    # Pick encoding order based on BOM / null-byte heuristic.
    # UTF-16 files have a BOM (FF FE or FE FF) or dense null bytes; otherwise
    # try single-byte codecs *before* UTF-16 so that CP1252/Latin-1 special
    # chars (e.g. en-dash 0x96) don't cause UTF-8 to fail and then get
    # mis-decoded as UTF-16 LE pairs, producing garbled CJK column names.
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        enc_order = ("utf-16", "utf-16-le", "utf-16-be")
    elif raw[:3] == b'\xef\xbb\xbf':
        enc_order = ("utf-8-sig",)
    elif raw[:200].count(b'\x00') / max(len(raw[:200]), 1) > 0.3:
        enc_order = ("utf-16", "utf-16-le", "utf-16-be", "cp1252", "latin-1")
    else:
        enc_order = ("utf-8-sig", "utf-8", "cp1252", "latin-1", "utf-16", "utf-16-le", "utf-16-be")

    text = None
    for enc in enc_order:
        try:
            candidate = raw.decode(enc)
            # Reject if too many null bytes -- UTF-16 decoded as a single-byte codec
            if candidate.count('\x00') > len(candidate) * 0.2:
                continue
            text = candidate
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if text is None:
        raise HTTPException(400, "Could not decode CSV -- please save as UTF-8 or UTF-16")

    # Strip BOM character that may remain after decoding
    text = text.lstrip('﻿')

    # Try to auto-detect delimiter; fall back to comma then semicolon
    sample = text[:4096]
    detected_dialect = None
    try:
        detected_dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        pass

    def _try_parse(dialect_or_delimiter):
        if isinstance(dialect_or_delimiter, str):
            r = csv.DictReader(io.StringIO(text), delimiter=dialect_or_delimiter)
        else:
            r = csv.DictReader(io.StringIO(text), dialect=dialect_or_delimiter)
        fnames = r.fieldnames or []
        # Strip BOM and whitespace from field names when normalizing
        norm = {(f or "").strip().lstrip('﻿').lower() for f in fnames}
        return r, norm, fnames

    reader = None
    fieldnames_raw = []
    for candidate in ([detected_dialect] if detected_dialect else []) + [",", ";", "\t"]:
        if candidate is None:
            continue
        r, norm_fnames, raw_fnames = _try_parse(candidate)
        if {"name", "sku"} <= norm_fnames:
            reader = r
            fieldnames = norm_fnames
            fieldnames_raw = raw_fnames
            break

    if reader is None:
        # Still couldn't find required columns -- try once more with comma to get field list for error
        r, norm_fnames, raw_fnames = _try_parse(",")
        found = sorted(raw_fnames) if raw_fnames else []
        detail = "CSV missing required columns: 'name' and 'sku'."
        if found:
            detail += f" Columns found: {found}. Make sure your CSV header row has exactly 'name' and 'sku' columns."
        else:
            detail += " No columns detected -- check that the file is a valid CSV."
        raise HTTPException(400, detail)

    existing_q = await db.execute(
        select(SupplierProduct).where(SupplierProduct.supplier_id == supplier_id)
    )
    by_sku: dict[str, SupplierProduct] = {sp.sku: sp for sp in existing_q.scalars().all()}

    created = updated = 0
    errors: list[str] = []
    seen_skus: set[str] = set()

    for idx, row in enumerate(reader, start=2):  # row 1 is header
        norm = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        sku = norm.get("sku", "")
        name = norm.get("name", "")
        if not sku or not name:
            errors.append(f"Row {idx}: missing name or sku")
            continue
        if sku in seen_skus:
            errors.append(f"Row {idx}: duplicate SKU '{sku}' in file")
            continue
        seen_skus.add(sku)

        try:
            raw_price = norm.get("unit_price") or ""
            raw_price = raw_price.replace("$", "").replace(",", "").strip()
            unit_price = Decimal(raw_price) if raw_price else Decimal("0")
        except (InvalidOperation, KeyError):
            errors.append(f"Row {idx} (SKU {sku}): invalid unit_price")
            continue
        try:
            raw_qty = norm.get("stock_quantity") or ""
            raw_qty = raw_qty.replace(",", "").strip()
            stock_quantity = int(raw_qty) if raw_qty else 0
        except (ValueError, KeyError):
            errors.append(f"Row {idx} (SKU {sku}): invalid stock_quantity")
            continue

        def _opt_dec(key: str):
            raw = norm.get(key) or ""
            if not raw:
                return None
            try:
                return Decimal(raw)
            except InvalidOperation:
                errors.append(f"Row {idx} (SKU {sku}): invalid {key}")
                return "__INVALID__"

        weight = _opt_dec("weight")
        length = _opt_dec("length")
        width = _opt_dec("width")
        height = _opt_dec("height")
        if any(v == "__INVALID__" for v in (weight, length, width, height)):
            continue

        sp = by_sku.get(sku)
        if sp:
            sp.name = name
            sp.unit_price = unit_price
            sp.stock_quantity = stock_quantity
            if weight is not None: sp.weight = weight
            if length is not None: sp.length = length
            if width is not None: sp.width = width
            if height is not None: sp.height = height
            updated += 1
        else:
            sp = SupplierProduct(
                supplier_id=supplier_id,
                name=name,
                sku=sku,
                unit_price=unit_price,
                stock_quantity=stock_quantity,
                weight=weight,
                length=length,
                width=width,
                height=height,
            )
            db.add(sp)
            by_sku[sku] = sp
            created += 1

    await db.commit()
    return {"created": created, "updated": updated, "errors": errors}


@router.get("/{supplier_id}/products/{sp_id}", response_model=SupplierProductOut)
async def get_supplier_product(supplier_id: int, sp_id: int, db: AsyncSession = Depends(get_db)):
    sp = await _get_sp_or_404(supplier_id, sp_id, db)
    return await _supplier_product_out(sp, db)


@router.patch("/{supplier_id}/products/{sp_id}", response_model=SupplierProductOut)
async def update_supplier_product(
    supplier_id: int, sp_id: int, body: SupplierProductUpdate, db: AsyncSession = Depends(get_db)
):
    sp = await _get_sp_or_404(supplier_id, sp_id, db)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(sp, k, v)
    await db.commit()
    await db.refresh(sp)
    return await _supplier_product_out(sp, db)


@router.delete("/{supplier_id}/products/{sp_id}", status_code=204)
async def delete_supplier_product(supplier_id: int, sp_id: int, db: AsyncSession = Depends(get_db)):
    sp = await _get_sp_or_404(supplier_id, sp_id, db)
    await db.delete(sp)
    await db.commit()


# --- Supplier orders (only own line items) ---

@router.get("/{supplier_id}/orders")
async def supplier_orders(
    supplier_id: int,
    skip: int = 0,
    limit: int = 200,
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    await _get_or_404(supplier_id, db)
    q = select(OrderLineItem).where(OrderLineItem.supplier_id == supplier_id)
    if status == "unfulfilled":
        q = q.where(OrderLineItem.fulfill_status == FulfillStatus.unfulfilled)
    elif status == "pending":
        q = q.where(OrderLineItem.fulfill_status == FulfillStatus.pending)
    elif status == "drop_off":
        q = q.where(OrderLineItem.fulfill_status == FulfillStatus.drop_off)
    elif status == "shipped":
        q = q.where(OrderLineItem.fulfill_status.in_([FulfillStatus.shipped, FulfillStatus.delivered]))
    result = await db.execute(
        select(OrderLineItem)
        .where(OrderLineItem.supplier_id == supplier_id)
        .order_by(OrderLineItem.id.desc())
        .offset(skip).limit(limit)
    )
    items = list(result.scalars().all())

    order_ids = list({li.order_id for li in items})
    orders_map: dict[int, Order] = {}
    if order_ids:
        order_q = await db.execute(select(Order).where(Order.id.in_(order_ids)))
        orders_map = {o.id: o for o in order_q.scalars().all()}

    label_ids = list({li.label_id for li in items if li.label_id is not None})
    labels_map: dict[int, ShippingLabel] = {}
    if label_ids:
        label_q = await db.execute(select(ShippingLabel).where(ShippingLabel.id.in_(label_ids)))
        labels_map = {l.id: l for l in label_q.scalars().all()}

    out = []
    for li in items:
        order = orders_map.get(li.order_id)
        label = labels_map.get(li.label_id) if li.label_id else None
        base = {
            "order_line_item_id": li.id,
            "order_id": li.order_id,
            "external_order_id": order.external_order_id if order else None,
            "marketplace": order.marketplace if order else None,
            "ordered_at": order.ordered_at.isoformat() if order else None,
            "buyer_name": order.buyer_name if order else None,
            "order_status": order.status if order else None,
            "shipping_address": order.shipping_address if order else None,
            "price": float(li.price),
            "base_cost": float(li.base_cost),
            "li_quantity": li.quantity,
            "label_id": li.label_id,
            "label_url": label.label_url if label else None,
            "label_has_pdf": bool(label and label.label_data) if label else False,
        }
        fi_res = await db.execute(
            select(OrderFulfillmentItem).where(OrderFulfillmentItem.order_line_item_id == li.id)
        )
        fis = list(fi_res.scalars().all())
        if fis:
            for fi in fis:
                sp = await db.get(SupplierProduct, fi.supplier_product_id)
                out.append({
                    **base,
                    "item_key": f"fi_{fi.id}",
                    "product_name": sp.name if sp else li.product_name,
                    "sku": sp.sku if sp else li.sku,
                    "image_url": sp.image_url if sp else None,
                    "quantity": fi.quantity,
                    "fulfill_status": fi.fulfill_status,
                    "tracking_number": fi.tracking_number or li.tracking_number,
                    "fulfilled_at": (fi.fulfilled_at.isoformat() if fi.fulfilled_at
                                    else (li.fulfilled_at.isoformat() if li.fulfilled_at else None)),
                })
        else:
            resolved = False
            if li.product_id:
                comp_res = await db.execute(
                    select(ProductComponent)
                    .join(SupplierProduct, ProductComponent.supplier_product_id == SupplierProduct.id)
                    .where(
                        ProductComponent.product_id == li.product_id,
                        SupplierProduct.supplier_id == supplier_id,
                    )
                )
                comps = list(comp_res.scalars().all())
                if comps:
                    for comp in comps:
                        sp = await db.get(SupplierProduct, comp.supplier_product_id)
                        out.append({
                            **base,
                            "item_key": f"comp_{comp.id}_{li.id}",
                            "product_name": sp.name if sp else li.product_name,
                            "sku": sp.sku if sp else li.sku,
                            "image_url": sp.image_url if sp else None,
                            "quantity": comp.quantity * li.quantity,
                            "fulfill_status": li.fulfill_status,
                            "tracking_number": li.tracking_number,
                            "fulfilled_at": li.fulfilled_at.isoformat() if li.fulfilled_at else None,
                        })
                    resolved = True
            if not resolved:
                out.append({
                    **base,
                    "item_key": f"li_{li.id}",
                    "product_name": li.product_name,
                    "sku": li.sku,
                    "image_url": None,
                    "quantity": li.quantity,
                    "fulfill_status": li.fulfill_status,
                    "tracking_number": li.tracking_number,
                    "fulfilled_at": li.fulfilled_at.isoformat() if li.fulfilled_at else None,
                })
    return out


# --- Invoices ---

@router.get("/{supplier_id}/invoices", response_model=list[InvoiceOut])
async def list_invoices(supplier_id: int, db: AsyncSession = Depends(get_db)):
    await _get_or_404(supplier_id, db)
    result = await db.execute(select(Invoice).where(Invoice.supplier_id == supplier_id))
    invoices = result.scalars().all()
    out = []
    for inv in invoices:
        li_result = await db.execute(select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == inv.id))
        li_list = li_result.scalars().all()
        inv_dict = {c.name: getattr(inv, c.name) for c in inv.__table__.columns}
        inv_dict["line_items"] = [
            {c.name: getattr(li, c.name) for c in li.__table__.columns}
            for li in li_list
        ]
        out.append(InvoiceOut(**inv_dict))
    return out


@router.get("/{supplier_id}/invoices/preview-from-orders", response_model=InvoicePreviewResponse)
async def preview_invoice_from_orders(supplier_id: int, db: AsyncSession = Depends(get_db)):
    """Return fulfilled order line items for this supplier that have not yet been invoiced."""
    supplier = await _get_or_404(supplier_id, db)

    invoiced_ids_result = await db.execute(
        select(InvoiceLineItem.order_line_item_id).where(InvoiceLineItem.order_line_item_id.isnot(None))
    )
    invoiced_ids = {r for r in invoiced_ids_result.scalars().all()}

    result = await db.execute(
        select(OrderLineItem)
        .where(
            OrderLineItem.supplier_id == supplier_id,
            OrderLineItem.fulfill_status.in_([FulfillStatus.shipped, FulfillStatus.delivered]),
        )
        .order_by(OrderLineItem.order_id)
    )
    line_items = result.scalars().all()

    order_ids = {li.order_id for li in line_items}
    orders_by_id: dict[int, Order] = {}
    if order_ids:
        ord_result = await db.execute(select(Order).where(Order.id.in_(order_ids)))
        for o in ord_result.scalars().all():
            orders_by_id[o.id] = o

    items = []
    for li in line_items:
        if li.id in invoiced_ids:
            continue
        unit_cost = li.base_cost
        total_cost = unit_cost * li.quantity
        order = orders_by_id.get(li.order_id)
        items.append(InvoicePreviewItem(
            order_line_item_id=li.id,
            order_id=li.order_id,
            order_external_id=order.external_order_id if order else None,
            product_name=li.product_name,
            sku=li.sku,
            quantity=li.quantity,
            unit_cost=unit_cost,
            total_cost=total_cost,
            fulfill_status=li.fulfill_status.value,
            fulfilled_at=li.fulfilled_at,
        ))

    total = sum(i.total_cost for i in items)
    return InvoicePreviewResponse(
        supplier_id=supplier_id,
        supplier_name=supplier.name,
        items=items,
        total_amount=total,
    )


@router.post("/{supplier_id}/invoices/create-from-orders", response_model=InvoiceOut, status_code=201)
async def create_invoice_from_orders(supplier_id: int, body: InvoiceFromOrdersCreate, db: AsyncSession = Depends(get_db)):
    """Create an invoice from fulfilled order line items with optional cost adjustments."""
    await _get_or_404(supplier_id, db)

    if not body.items:
        raise HTTPException(400, "No line items provided")

    item_ids = [it.order_line_item_id for it in body.items]
    already_result = await db.execute(
        select(InvoiceLineItem.order_line_item_id).where(
            InvoiceLineItem.order_line_item_id.in_(item_ids)
        )
    )
    already_invoiced = {r for r in already_result.scalars().all()}
    if already_invoiced:
        raise HTTPException(400, f"Line items already invoiced: {sorted(already_invoiced)}")

    li_result = await db.execute(
        select(OrderLineItem).where(OrderLineItem.id.in_(item_ids))
    )
    db_items = {li.id: li for li in li_result.scalars().all()}

    dates = [li.fulfilled_at or li.order.created_at for li in db_items.values() if li.fulfilled_at]
    now = datetime.now(timezone.utc)
    period_start = min(dates) if dates else now
    period_end = max(dates) if dates else now

    total = sum(it.total_amount for it in body.items)
    inv_number = f"INV-{supplier_id}-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    invoice = Invoice(
        supplier_id=supplier_id,
        invoice_number=inv_number,
        period_start=period_start,
        period_end=period_end,
        total_amount=total,
        notes=body.notes,
    )
    db.add(invoice)
    await db.flush()

    for it in body.items:
        db.add(InvoiceLineItem(
            invoice_id=invoice.id,
            order_line_item_id=it.order_line_item_id,
            description=it.description,
            quantity=it.quantity,
            unit_amount=it.unit_amount,
            total_amount=it.total_amount,
        ))

    await db.commit()
    await db.refresh(invoice)
    li_result2 = await db.execute(select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == invoice.id))
    li_list = li_result2.scalars().all()
    inv_dict = {c.name: getattr(invoice, c.name) for c in invoice.__table__.columns}
    inv_dict["line_items"] = [{c.name: getattr(li, c.name) for c in li.__table__.columns} for li in li_list]
    return InvoiceOut(**inv_dict)


@router.post("/{supplier_id}/invoices", response_model=InvoiceOut, status_code=201)
async def create_invoice(supplier_id: int, body: InvoiceCreate, db: AsyncSession = Depends(get_db)):
    await _get_or_404(supplier_id, db)
    total = sum(li.total_amount for li in body.line_items)
    inv_number = f"INV-{supplier_id}-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    invoice = Invoice(
        supplier_id=supplier_id,
        invoice_number=inv_number,
        period_start=body.period_start,
        period_end=body.period_end,
        total_amount=total,
        notes=body.notes,
    )
    db.add(invoice)
    await db.flush()

    for li in body.line_items:
        db.add(InvoiceLineItem(invoice_id=invoice.id, **li.model_dump()))

    await db.commit()
    await db.refresh(invoice)
    li_result = await db.execute(select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == invoice.id))
    li_list = li_result.scalars().all()
    inv_dict = {c.name: getattr(invoice, c.name) for c in invoice.__table__.columns}
    inv_dict["line_items"] = [{c.name: getattr(li, c.name) for c in li.__table__.columns} for li in li_list]
    return InvoiceOut(**inv_dict)


@router.patch("/{supplier_id}/invoices/{invoice_id}", response_model=InvoiceOut)
async def update_invoice(supplier_id: int, invoice_id: int, body: InvoiceUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Invoice).where(Invoice.id == invoice_id, Invoice.supplier_id == supplier_id))
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(404, "Invoice not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(invoice, k, v)
    await db.commit()
    await db.refresh(invoice)
    li_result = await db.execute(select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == invoice.id))
    li_list = li_result.scalars().all()
    inv_dict = {c.name: getattr(invoice, c.name) for c in invoice.__table__.columns}
    inv_dict["line_items"] = [{c.name: getattr(li, c.name) for c in li.__table__.columns} for li in li_list]
    return InvoiceOut(**inv_dict)


class SendOrdersRequest(BaseModel):
    order_ids: list[int]
    notes: str | None = None


@router.post("/{supplier_id}/send-orders")
async def send_orders_to_supplier(
    supplier_id: int,
    body: SendOrdersRequest,
    db: AsyncSession = Depends(get_db),
):
    """Build merged label PDF + invoice PDF and email them to the supplier."""
    import httpx
    from collections import defaultdict
    from app.integrations.pdf_labels import (
        PackItem, LabelEntry, decode_label_data, concat_label_pdfs,
        build_label_from_png, build_batch_label_pdf,
    )
    from app.api.v1.orders import _catalog_items_for_line_item
    from app.integrations.invoice_pdf import build_send_order_pdf
    from app.integrations.email_service import send_email

    supplier = await _get_or_404(supplier_id, db)
    if not body.order_ids:
        raise HTTPException(400, "No orders selected")

    ord_res = await db.execute(select(Order).where(Order.id.in_(body.order_ids)))
    orders_map: dict[int, Order] = {o.id: o for o in ord_res.scalars().all()}

    li_res = await db.execute(
        select(OrderLineItem).where(
            OrderLineItem.supplier_id == supplier_id,
            OrderLineItem.order_id.in_(body.order_ids),
        ).order_by(OrderLineItem.order_id)
    )
    all_lis = list(li_res.scalars().all())
    if not all_lis:
        raise HTTPException(404, "No line items found for the selected orders and this supplier")

    order_invoice_rows: list[dict] = []

    for li in all_lis:
        order = orders_map.get(li.order_id)
        ext_id = order.external_order_id if order else None

        fi_res = await db.execute(
            select(OrderFulfillmentItem).where(OrderFulfillmentItem.order_line_item_id == li.id)
        )
        fis = list(fi_res.scalars().all())
        if fis:
            for fi in fis:
                sp = await db.get(SupplierProduct, fi.supplier_product_id)
                if sp:
                    order_invoice_rows.append({
                        "order_id": li.order_id,
                        "external_order_id": ext_id,
                        "catalog_name": sp.name,
                        "sku": sp.sku,
                        "quantity": fi.quantity,
                        "unit_cost": float(sp.unit_price),
                        "total": float(sp.unit_price) * fi.quantity,
                    })
            continue

        if li.product_id:
            comp_res = await db.execute(
                select(ProductComponent)
                .join(SupplierProduct, ProductComponent.supplier_product_id == SupplierProduct.id)
                .where(
                    ProductComponent.product_id == li.product_id,
                    SupplierProduct.supplier_id == supplier_id,
                )
            )
            comps = list(comp_res.scalars().all())
            if comps:
                for comp in comps:
                    sp = await db.get(SupplierProduct, comp.supplier_product_id)
                    if sp:
                        qty = comp.quantity * li.quantity
                        order_invoice_rows.append({
                            "order_id": li.order_id,
                            "external_order_id": ext_id,
                            "catalog_name": sp.name,
                            "sku": sp.sku,
                            "quantity": qty,
                            "unit_cost": float(sp.unit_price),
                            "total": float(sp.unit_price) * qty,
                        })
                continue

        order_invoice_rows.append({
            "order_id": li.order_id,
            "external_order_id": ext_id,
            "catalog_name": li.product_name or "Unknown",
            "sku": li.sku,
            "quantity": li.quantity,
            "unit_cost": float(li.base_cost),
            "total": float(li.base_cost) * li.quantity,
        })

    total_amount = round(sum(r["total"] for r in order_invoice_rows), 2)

    labeled_by_label: dict[int, list] = defaultdict(list)
    for li in all_lis:
        if li.label_id:
            labeled_by_label[li.label_id].append(li)

    pdf_pages: list[bytes] = []
    for label_id, label_lis in labeled_by_label.items():
        label = await db.get(ShippingLabel, label_id)
        if not label or label.supplier_id != supplier_id:
            continue

        if label.label_data:
            pdf = decode_label_data(label.label_data)
            if pdf:
                pdf_pages.append(pdf)
                continue

        if not label.label_url:
            continue
        try:
            async with httpx.AsyncClient(timeout=20) as http:
                r = await http.get(label.label_url)
            if not r.is_success:
                continue
            content = r.content
        except Exception:
            continue

        pack_items: list[PackItem] = []
        for li in label_lis:
            pack_items.extend(await _catalog_items_for_line_item(li, db))

        order = orders_map.get(label_lis[0].order_id)
        entry = LabelEntry(
            order_label=(order.external_order_id if order else f"Label #{label_id}"),
            ship_to=None,
            tracking_number=label.tracking_number,
            label_pdf=None,
            items=pack_items,
        )
        try:
            if content[:8] == b"\x89PNG\r\n\x1a\n":
                pdf_pages.append(build_label_from_png(content, entry))
            else:
                entry.label_pdf = content
                pdf_pages.append(build_batch_label_pdf([entry]))
        except Exception:
            continue

    label_pdf_bytes = concat_label_pdfs(pdf_pages) if pdf_pages else None
    label_pages = len(pdf_pages)

    now = datetime.now(timezone.utc)
    inv_number = f"INV-{supplier_id}-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    invoice = Invoice(
        supplier_id=supplier_id,
        invoice_number=inv_number,
        period_start=now,
        period_end=now,
        total_amount=Decimal(str(total_amount)),
        status="sent",
        notes=body.notes or f"Send-orders for {len(body.order_ids)} order(s)",
    )
    db.add(invoice)
    await db.flush()

    for row in order_invoice_rows:
        desc = f"Order #{row['order_id']}"
        if row.get("external_order_id"):
            desc += f" ({row['external_order_id']})"
        desc += f": {row['catalog_name']}"
        if row.get("sku"):
            desc += f" [{row['sku']}]"
        db.add(InvoiceLineItem(
            invoice_id=invoice.id,
            order_line_item_id=None,
            description=desc,
            quantity=row["quantity"],
            unit_amount=Decimal(str(round(row["unit_cost"], 2))),
            total_amount=Decimal(str(round(row["total"], 2))),
        ))

    await db.commit()

    invoice_pdf_bytes = build_send_order_pdf(
        invoice_number=inv_number,
        invoice_date=now,
        supplier_name=supplier.name,
        supplier_email=supplier.email,
        order_items=order_invoice_rows,
        total_amount=total_amount,
        notes=body.notes,
    )

    email_sent = False
    email_error = None
    if supplier.email:
        try:
            order_count = len(body.order_ids)
            safe_inv = inv_number.replace("/", "-")
            attachments: list[tuple[str, bytes, str]] = [
                (f"{safe_inv}.pdf", invoice_pdf_bytes, "application/pdf"),
            ]
            if label_pdf_bytes:
                attachments.append(("shipping_labels.pdf", label_pdf_bytes, "application/pdf"))

            order_rows_html = "".join(
                f"<tr><td>#{oid}</td><td>{orders_map[oid].external_order_id or ''}</td></tr>"
                for oid in body.order_ids
                if oid in orders_map
            )
            html_body = f"""
<html><body style="font-family:Arial,sans-serif;color:#1f2937">
<h2 style="color:#1e40af">New Purchase Order — {inv_number}</h2>
<p>Dear {supplier.name},</p>
<p>Please find attached a new purchase order for <strong>{order_count}</strong> order(s)
totalling <strong>${total_amount:.2f}</strong>.</p>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-size:14px">
  <tr style="background:#1e40af;color:white"><th>Order #</th><th>Reference</th></tr>
  {order_rows_html}
</table>
{'<p>Shipping labels are attached — please print and affix them to each package.</p>' if label_pdf_bytes else ''}
<p>Please fulfill and ship the items at your earliest convenience.</p>
{f'<p><em>Note: {body.notes}</em></p>' if body.notes else ''}
<p>Thank you,<br>Supplier Management</p>
</body></html>"""

            await send_email(
                to=supplier.email,
                subject=f"New Orders — {inv_number} ({order_count} order{'s' if order_count != 1 else ''})",
                html_body=html_body,
                attachments=attachments,
            )
            email_sent = True
        except Exception as exc:
            email_error = str(exc)
    else:
        email_error = "Supplier has no email address — invoice created but not sent."

    return {
        "success": True,
        "invoice_id": invoice.id,
        "invoice_number": inv_number,
        "orders_count": len(body.order_ids),
        "items_count": len(order_invoice_rows),
        "total_amount": total_amount,
        "label_pages": label_pages,
        "email_sent": email_sent,
        "email_error": email_error,
    }


async def _get_or_404(supplier_id: int, db: AsyncSession) -> Supplier:
    s = await db.get(Supplier, supplier_id)
    if not s:
        raise HTTPException(404, "Supplier not found")
    return s


async def _get_sp_or_404(supplier_id: int, sp_id: int, db: AsyncSession) -> SupplierProduct:
    result = await db.execute(
        select(SupplierProduct).where(
            SupplierProduct.id == sp_id,
            SupplierProduct.supplier_id == supplier_id,
        )
    )
    sp = result.scalar_one_or_none()
    if not sp:
        raise HTTPException(404, "Supplier product not found")
    return sp


async def _supplier_product_out(sp: SupplierProduct, db: AsyncSession) -> SupplierProductOut:
    pending_result = await db.execute(
        select(func.coalesce(func.sum(OrderFulfillmentItem.quantity), 0)).where(
            OrderFulfillmentItem.supplier_product_id == sp.id,
            OrderFulfillmentItem.fulfill_status.in_([FulfillStatus.unfulfilled, FulfillStatus.pending]),
        )
    )
    sold_result = await db.execute(
        select(func.coalesce(func.sum(OrderFulfillmentItem.quantity), 0)).where(
            OrderFulfillmentItem.supplier_product_id == sp.id,
            OrderFulfillmentItem.fulfill_status.in_([FulfillStatus.shipped, FulfillStatus.delivered]),
        )
    )
    return SupplierProductOut(
        id=sp.id,
        supplier_id=sp.supplier_id,
        name=sp.name,
        sku=sp.sku,
        unit_price=sp.unit_price,
        stock_quantity=sp.stock_quantity,
        short_name=sp.short_name,
        pending_quantity=int(pending_result.scalar()),
        sold_quantity=int(sold_result.scalar()),
        weight=sp.weight,
        length=sp.length,
        width=sp.width,
        height=sp.height,
        image_url=sp.image_url,
        created_at=sp.created_at,
        updated_at=sp.updated_at,
    )
