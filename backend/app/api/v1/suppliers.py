from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.models.supplier import Supplier, Invoice, InvoiceLineItem, SupplierProduct
from app.models.product import ProductSupplier
from app.models.order import Order, OrderLineItem, OrderFulfillmentItem, FulfillStatus
from app.schemas.supplier import (
    SupplierCreate, SupplierUpdate, SupplierOut, SupplierListOut,
    InvoiceCreate, InvoiceUpdate, InvoiceOut
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


CATALOG_CSV_COLUMNS = ["name", "sku", "unit_price", "stock_quantity"]


@router.get("/{supplier_id}/products/export.csv")
async def export_supplier_catalog(supplier_id: int, db: AsyncSession = Depends(get_db)):
    supplier = await _get_or_404(supplier_id, db)
    result = await db.execute(
        select(SupplierProduct).where(SupplierProduct.supplier_id == supplier_id)
    )
    products = result.scalars().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CATALOG_CSV_COLUMNS)
    for sp in products:
        writer.writerow([sp.name, sp.sku, f"{sp.unit_price:.2f}", sp.stock_quantity])

    safe_name = "".join(c if c.isalnum() else "_" for c in supplier.name)[:40] or "supplier"
    filename = f"{safe_name}_catalog_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{supplier_id}/products/template.csv")
async def supplier_catalog_template(supplier_id: int, db: AsyncSession = Depends(get_db)):
    await _get_or_404(supplier_id, db)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CATALOG_CSV_COLUMNS)
    writer.writerow(["Example Product", "SKU-001", "9.99", "100"])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
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
    text = None
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise HTTPException(400, "Could not decode CSV — please save as UTF-8")

    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise HTTPException(400, "CSV is empty")

    fieldnames = {(f or "").strip().lower() for f in reader.fieldnames}
    missing = {"name", "sku"} - fieldnames
    if missing:
        raise HTTPException(400, f"CSV missing required columns: {sorted(missing)}")

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
            unit_price = Decimal(norm["unit_price"]) if norm.get("unit_price") else Decimal("0")
        except (InvalidOperation, KeyError):
            errors.append(f"Row {idx} (SKU {sku}): invalid unit_price")
            continue
        try:
            stock_quantity = int(norm["stock_quantity"]) if norm.get("stock_quantity") else 0
        except (ValueError, KeyError):
            errors.append(f"Row {idx} (SKU {sku}): invalid stock_quantity")
            continue

        sp = by_sku.get(sku)
        if sp:
            sp.name = name
            sp.unit_price = unit_price
            sp.stock_quantity = stock_quantity
            updated += 1
        else:
            sp = SupplierProduct(
                supplier_id=supplier_id,
                name=name,
                sku=sku,
                unit_price=unit_price,
                stock_quantity=stock_quantity,
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
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    await _get_or_404(supplier_id, db)
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

    out = []
    for li in items:
        order = orders_map.get(li.order_id)
        out.append({
            "id": li.id,
            "order_id": li.order_id,
            "external_order_id": order.external_order_id if order else None,
            "marketplace": order.marketplace if order else None,
            "ordered_at": order.ordered_at.isoformat() if order else None,
            "buyer_name": order.buyer_name if order else None,
            "order_status": order.status if order else None,
            "product_id": li.product_id,
            "product_name": li.product_name,
            "sku": li.sku,
            "quantity": li.quantity,
            "price": float(li.price),
            "base_cost": float(li.base_cost),
            "fulfill_status": li.fulfill_status,
            "tracking_number": li.tracking_number,
            "label_id": li.label_id,
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
        pending_quantity=int(pending_result.scalar()),
        sold_quantity=int(sold_result.scalar()),
        created_at=sp.created_at,
        updated_at=sp.updated_at,
    )
