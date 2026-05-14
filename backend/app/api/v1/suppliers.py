from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.core.database import get_db
from app.models.supplier import Supplier, Invoice, InvoiceLineItem
from app.models.product import ProductSupplier
from app.models.order import OrderLineItem
from app.schemas.supplier import (
    SupplierCreate, SupplierUpdate, SupplierOut, SupplierListOut,
    InvoiceCreate, InvoiceUpdate, InvoiceOut
)
import uuid
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
            id=s.id, name=s.name, email=s.email, city=s.city, country=s.country,
            is_active=s.is_active,
            product_count=len(ps_list),
            total_stock=sum(ps.stock for ps in ps_list),
        ))
    return out


@router.post("", response_model=SupplierOut, status_code=201)
async def create_supplier(body: SupplierCreate, db: AsyncSession = Depends(get_db)):
    supplier = Supplier(**body.model_dump())
    db.add(supplier)
    await db.commit()
    await db.refresh(supplier)
    return supplier


@router.get("/{supplier_id}", response_model=SupplierOut)
async def get_supplier(supplier_id: int, db: AsyncSession = Depends(get_db)):
    return await _get_or_404(supplier_id, db)


@router.patch("/{supplier_id}", response_model=SupplierOut)
async def update_supplier(supplier_id: int, body: SupplierUpdate, db: AsyncSession = Depends(get_db)):
    supplier = await _get_or_404(supplier_id, db)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(supplier, k, v)
    await db.commit()
    await db.refresh(supplier)
    return supplier


@router.delete("/{supplier_id}", status_code=204)
async def delete_supplier(supplier_id: int, db: AsyncSession = Depends(get_db)):
    supplier = await _get_or_404(supplier_id, db)
    await db.delete(supplier)
    await db.commit()


# --- Supplier inventory ---

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
        .offset(skip).limit(limit)
    )
    items = result.scalars().all()
    return [
        {
            "id": li.id,
            "order_id": li.order_id,
            "product_id": li.product_id,
            "product_name": li.product_name,
            "sku": li.sku,
            "quantity": li.quantity,
            "price": float(li.price),
            "base_cost": float(li.base_cost),
            "fulfill_status": li.fulfill_status,
            "tracking_number": li.tracking_number,
        }
        for li in items
    ]


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
