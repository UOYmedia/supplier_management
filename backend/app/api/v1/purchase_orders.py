from __future__ import annotations

import os
import tempfile
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.daily_balance import DailyBalance
from app.models.order import Order, OrderLineItem
from app.models.purchase_order import PurchaseOrder
from app.models.supplier import Supplier, SupplierProduct
from app.schemas.purchase_order import (
    BalanceOut,
    POCreate,
    PODailyResponse,
    POPeriodResponse,
    PORead,
    POStatusUpdate,
    RequestCreate,
    RequestRead,
    RequestStatusUpdate,
    SKUItemOut,
)
from generate_po import generate_po_pdf

router = APIRouter(prefix="/purchase-orders", tags=["purchase-orders"])


# ── helpers ───────────────────────────────────────────────────────────────────

def _compute_item(
    po: PurchaseOrder,
    available: int,
    ordered: int,
    unit_cost: float,
) -> SKUItemOut:
    gap = available - ordered
    oversold = max(0, -gap)
    avail_final = max(0, gap)
    total_cost = ordered * unit_cost
    oversold_value = oversold * unit_cost
    avail_value = avail_final * unit_cost

    if gap > 5:
        status = "ok"
    elif gap > 0:
        status = "low"
    elif gap == 0:
        status = "low"
    else:
        status = "oversold"

    return SKUItemOut(
        sku=po.sku,
        supplier=po.supplier,
        ordered=ordered,
        available=available,
        unit_cost=unit_cost,
        gap=gap,
        oversold=oversold,
        avail_final=avail_final,
        total_cost=total_cost,
        oversold_value=oversold_value,
        avail_value=avail_value,
        status=status,
        po_id=po.id,
        po_status=po.status,
    )


async def _get_sold_7d(db: AsyncSession, sku: str, ref_date: date) -> int:
    """Sum of order line item quantities for a SKU in the past 7 days."""
    since = datetime(ref_date.year, ref_date.month, ref_date.day, tzinfo=timezone.utc) - timedelta(days=7)
    result = await db.execute(
        select(func.coalesce(func.sum(OrderLineItem.quantity), 0))
        .join(Order, Order.id == OrderLineItem.order_id)
        .where(
            OrderLineItem.sku == sku,
            Order.ordered_at >= since,
        )
    )
    return int(result.scalar() or 0)


async def _get_starting_balance(db: AsyncSession, ref_date: date) -> float:
    """Ending balance of the previous day, else 0."""
    prev = ref_date - timedelta(days=1)
    result = await db.execute(
        select(DailyBalance).where(DailyBalance.date == prev)
    )
    row = result.scalar_one_or_none()
    return float(row.ending_balance) if row else 0.0


# ── GET /daily ────────────────────────────────────────────────────────────────

@router.get("/daily", response_model=PODailyResponse)
async def get_daily_po(
    date_str: str = Query(None, alias="date"),
    db: AsyncSession = Depends(get_db),
):
    ref_date: date
    if date_str:
        try:
            ref_date = date.fromisoformat(date_str)
        except ValueError:
            raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")
    else:
        ref_date = date.today()

    result = await db.execute(
        select(PurchaseOrder)
        .where(PurchaseOrder.created_date == ref_date,
               PurchaseOrder.record_type == "daily")
        .order_by(PurchaseOrder.supplier, PurchaseOrder.sku)
    )
    pos = result.scalars().all()

    items: list[SKUItemOut] = []
    for po in pos:
        sold_7d = await _get_sold_7d(db, po.sku, ref_date)
        # available = supplier-confirmed qty minus units sold this week
        available = max(0, po.qty_available - sold_7d)
        items.append(_compute_item(
            po=po,
            available=available,
            ordered=po.qty_ordered,
            unit_cost=float(po.unit_cost),
        ))

    starting_balance = await _get_starting_balance(db, ref_date)
    total_cost = sum(i.total_cost for i in items)
    available_value = sum(i.avail_value for i in items)
    oversold_value = sum(i.oversold_value for i in items)
    ending_balance = starting_balance - total_cost

    balance = BalanceOut(
        starting_balance=starting_balance,
        total_cost=total_cost,
        available_value=available_value,
        oversold_value=oversold_value,
        ending_balance=ending_balance,
    )

    return PODailyResponse(
        date=ref_date.isoformat(),
        items=items,
        balance=balance,
    )


# ── GET /period ───────────────────────────────────────────────────────────────

@router.get("/period", response_model=POPeriodResponse)
async def get_period_po(
    from_date: str = Query(...),
    to_date: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    try:
        fd = date.fromisoformat(from_date)
        td = date.fromisoformat(to_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="dates must be YYYY-MM-DD")

    if fd > td:
        raise HTTPException(status_code=422, detail="from_date must be <= to_date")

    result = await db.execute(
        select(PurchaseOrder)
        .where(
            PurchaseOrder.created_date >= fd,
            PurchaseOrder.created_date <= td,
            PurchaseOrder.record_type == "daily",
        )
        .order_by(PurchaseOrder.supplier, PurchaseOrder.sku, PurchaseOrder.created_date)
    )
    pos = result.scalars().all()

    # Aggregate per (supplier, sku):
    # - ordered: sum across all days in period
    # - available: latest day's value (snapshot, not cumulative)
    agg: dict[tuple[str, str], dict] = {}
    for po in pos:
        key = (po.supplier, po.sku)
        if key not in agg:
            agg[key] = {
                "po": po,
                "ordered": 0,
                "available": 0,
                "unit_cost": float(po.unit_cost),
            }
        agg[key]["ordered"] += po.qty_ordered
        # always overwrite with latest (rows ordered by created_date asc)
        agg[key]["available"] = po.qty_available

    items: list[SKUItemOut] = []
    for (supplier, sku), d in agg.items():
        items.append(_compute_item(
            po=d["po"],
            available=d["available"],
            ordered=d["ordered"],
            unit_cost=d["unit_cost"],
        ))

    starting_balance = await _get_starting_balance(db, fd)
    total_cost = sum(i.total_cost for i in items)
    available_value = sum(i.avail_value for i in items)
    oversold_value = sum(i.oversold_value for i in items)
    ending_balance = starting_balance - total_cost

    balance = BalanceOut(
        starting_balance=starting_balance,
        total_cost=total_cost,
        available_value=available_value,
        oversold_value=oversold_value,
        ending_balance=ending_balance,
    )

    return POPeriodResponse(
        from_date=fd.isoformat(),
        to_date=td.isoformat(),
        items=items,
        balance=balance,
    )


# ── GET /balance/today ────────────────────────────────────────────────────────

@router.get("/balance/today", response_model=BalanceOut)
async def get_today_balance(db: AsyncSession = Depends(get_db)):
    today = date.today()
    starting_balance = await _get_starting_balance(db, today)

    result = await db.execute(
        select(PurchaseOrder).where(PurchaseOrder.created_date == today,
                                   PurchaseOrder.record_type == "daily")
    )
    pos = result.scalars().all()

    total_cost = sum(float(p.unit_cost) * p.qty_ordered for p in pos)
    return BalanceOut(
        starting_balance=starting_balance,
        total_cost=total_cost,
        available_value=0.0,
        oversold_value=0.0,
        ending_balance=starting_balance - total_cost,
    )


# ── POST / ────────────────────────────────────────────────────────────────────

@router.post("/", response_model=PORead, status_code=201)
async def create_po(body: POCreate, db: AsyncSession = Depends(get_db)):
    po = PurchaseOrder(
        supplier=body.supplier,
        sku=body.sku,
        qty_ordered=body.qty_ordered,
        qty_available=body.qty_available,
        unit_cost=body.unit_cost,
        status="PENDING",
        po_number=body.po_number,
        created_date=body.created_date,
        notes=body.notes,
    )
    db.add(po)
    await db.commit()
    await db.refresh(po)
    return po


# ── PATCH /{id}/status ────────────────────────────────────────────────────────

@router.patch("/{po_id}/status", response_model=PORead)
async def update_po_status(
    po_id: int,
    body: POStatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(PurchaseOrder).where(PurchaseOrder.id == po_id))
    po = result.scalar_one_or_none()
    if not po:
        raise HTTPException(status_code=404, detail="PurchaseOrder not found")

    po.status = body.status
    if body.status == "PAID" and po.paid_date is None:
        po.paid_date = date.today()

    await db.commit()
    await db.refresh(po)
    return po


# ── GET /requests ─────────────────────────────────────────────────────────────

@router.get("/requests", response_model=list[RequestRead])
async def list_requests(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(PurchaseOrder)
        .where(PurchaseOrder.record_type == "request")
        .order_by(PurchaseOrder.requested_date.desc())
    )
    return result.scalars().all()


# ── POST /requests ─────────────────────────────────────────────────────────────

@router.post("/requests", response_model=RequestRead, status_code=201)
async def create_request(body: RequestCreate, db: AsyncSession = Depends(get_db)):
    today = date.today()
    # Resolve and store the supplier id so the PAID stock increment can match on
    # a stable key. Prefer the id sent by the client; fall back to the name.
    supplier_id = body.supplier_id
    if supplier_id is None:
        sup = (await db.execute(
            select(Supplier).where(Supplier.name == body.supplier)
        )).scalar_one_or_none()
        supplier_id = sup.id if sup else None
    po = PurchaseOrder(
        supplier=body.supplier,
        supplier_id=supplier_id,
        sku=body.sku,
        qty_ordered=body.qty_ordered,
        qty_available=body.qty_available,
        unit_cost=body.unit_cost,
        po_number=body.po_number,
        pic=body.pic,
        status="PENDING",
        amount_paid=0.0,
        requested_date=body.requested_date or today,
        created_date=today,
        notes=body.notes,
        record_type="request",
    )
    db.add(po)
    await db.commit()
    await db.refresh(po)
    return po


# ── PATCH /requests/{id}/status ───────────────────────────────────────────────

@router.patch("/requests/{po_id}/status", response_model=RequestRead)
async def update_request_status(
    po_id: int,
    body: RequestStatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(PurchaseOrder).where(PurchaseOrder.id == po_id))
    po = result.scalar_one_or_none()
    if not po:
        raise HTTPException(status_code=404, detail="PurchaseOrder not found")

    was_paid = po.status == "PAID"
    po.status = body.status

    if body.status == "PAID":
        po.approved_date = date.today()
        po.paid_date = date.today()
        if body.approved_by:
            po.approved_by = body.approved_by
        # Paying a request means the goods are now in the supplier's stock.
        # Only stock-type suppliers hold inventory, so the catalog quantity is
        # bumped here. Idempotent: skip if this request was already PAID.
        # The increment is staged on this same session (no commit of its own),
        # so the single commit below is the one atomic point: either both the
        # PAID status and the stock increment persist together, or neither does.
        if not was_paid:
            await _increment_supplier_stock(db, po)
    elif body.status == "PARTIALLY_PAID":
        if body.amount_paid is not None:
            po.amount_paid = body.amount_paid
        if body.approved_by:
            po.approved_by = body.approved_by

    # Commit status + stock change as one transaction. On any failure roll the
    # session back so nothing is half-applied (stock never moves without the
    # PAID status sticking, and vice versa) and the session is left clean.
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update request status")
    await db.refresh(po)
    return po


async def _increment_supplier_stock(db: AsyncSession, po: PurchaseOrder) -> None:
    """Add a paid request's qty into the matching SupplierProduct catalog row.

    Requests link the supplier by *supplier_id* (stable) and the item by *sku*.
    We match a stock-type supplier and its catalog SKU exactly; on no match we
    leave stock untouched rather than guess (a warning is logged). For older rows
    without a supplier_id we fall back to matching the supplier name.
    """
    sup = None
    if po.supplier_id is not None:
        sup = await db.get(Supplier, po.supplier_id)
    if sup is None:
        sup = (await db.execute(
            select(Supplier).where(Supplier.name == po.supplier)
        )).scalar_one_or_none()
    if sup is None or sup.supplier_type != "stock":
        return

    sp = (await db.execute(
        select(SupplierProduct).where(
            SupplierProduct.supplier_id == sup.id,
            SupplierProduct.sku == po.sku,
        )
    )).scalar_one_or_none()
    if sp is None:
        import logging
        logging.getLogger(__name__).warning(
            "PAID request %s: no catalog SKU '%s' for supplier '%s' — stock not incremented",
            po.id, po.sku, po.supplier,
        )
        return

    sp.stock_quantity = (sp.stock_quantity or 0) + (po.qty_ordered or 0)


# ── POST /generate-pdf ────────────────────────────────────────────────────────

class SupplierInfo(BaseModel):
    name: str = ""
    address: str = ""
    city: str = ""
    phone: str = ""
    email: str = ""


class BuyerInfo(BaseModel):
    name: str = ""
    company: str = ""
    email: str = ""
    address: str = ""


class Balance(BaseModel):
    total_cost: float = 0
    available_value: float = 0
    oversold_value: float = 0
    starting_balance: float = 0
    ending_balance: float = 0


class GeneratePDFRequest(BaseModel):
    supplier: str
    po_number: str
    date: str
    items: list[dict[str, Any]]
    supplier_info: SupplierInfo
    buyer_info: BuyerInfo
    balance: Balance


@router.post("/generate-pdf")
async def generate_pdf(body: GeneratePDFRequest):
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in body.po_number)
    output_path = os.path.join(tempfile.gettempdir(), f"{safe_name}.pdf")

    generate_po_pdf(
        output_path=output_path,
        supplier=body.supplier,
        po_number=body.po_number,
        date=body.date,
        items=body.items,
        supplier_info=body.supplier_info.model_dump(),
        buyer_info=body.buyer_info.model_dump(),
        balance=body.balance.model_dump(),
    )

    return FileResponse(
        path=output_path,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{safe_name}.pdf"'},
    )


# ── POST /seed-dev ────────────────────────────────────────────────────────────
# Guarded by DEBUG env var. Call once to populate test data, then remove.

SEED_ITEMS = [
    {"supplier": "JOE",   "sku": "Meyer Lemon Tree",       "qty_ordered": 5,  "qty_available": 8,  "unit_cost": 15.00},
    {"supplier": "JOE",   "sku": "Baby Breath",            "qty_ordered": 6,  "qty_available": 4,  "unit_cost": 5.00 },
    {"supplier": "JOE",   "sku": "Crown of Thorn Red",     "qty_ordered": 10, "qty_available": 7,  "unit_cost": 7.50 },
    {"supplier": "JOE",   "sku": "French Tarragon",        "qty_ordered": 4,  "qty_available": 12, "unit_cost": 5.00 },
    {"supplier": "SKY",   "sku": "Spanish Lavender",       "qty_ordered": 8,  "qty_available": 8,  "unit_cost": 5.00 },
    {"supplier": "SKY",   "sku": "English Lavender",       "qty_ordered": 4,  "qty_available": 10, "unit_cost": 5.00 },
    {"supplier": "SKY",   "sku": "Night Blooming Jasmine", "qty_ordered": 6,  "qty_available": 6,  "unit_cost": 6.50 },
    {"supplier": "SKY",   "sku": "Rasp Buddleia",          "qty_ordered": 5,  "qty_available": 3,  "unit_cost": 6.50 },
    {"supplier": "FAIRY", "sku": "Peppermint",             "qty_ordered": 3,  "qty_available": 5,  "unit_cost": 5.00 },
    {"supplier": "FAIRY", "sku": "Confederate Jasmine",    "qty_ordered": 7,  "qty_available": 7,  "unit_cost": 6.50 },
    {"supplier": "FAIRY", "sku": "Thai Constellation",     "qty_ordered": 2,  "qty_available": 4,  "unit_cost": 13.50},
]

PO_NUMBERS = {"JOE": "PO-2026-0623-JOE", "SKY": "PO-2026-0623-SKY", "FAIRY": "PO-2026-0623-FAIRY"}


@router.post("/seed-dev")
async def seed_dev(db: AsyncSession = Depends(get_db)):
    if os.getenv("DEBUG", "").lower() not in ("1", "true"):
        raise HTTPException(status_code=403, detail="Only available when DEBUG=true")

    from sqlalchemy import delete as sa_delete
    today = date.today()

    await db.execute(sa_delete(PurchaseOrder).where(PurchaseOrder.created_date == today))
    await db.commit()

    inserted = []
    for item in SEED_ITEMS:
        po = PurchaseOrder(
            supplier=item["supplier"],
            sku=item["sku"],
            qty_ordered=item["qty_ordered"],
            qty_available=item["qty_available"],
            unit_cost=item["unit_cost"],
            status="PAID",
            po_number=PO_NUMBERS[item["supplier"]],
            created_date=today,
            paid_date=today,
        )
        db.add(po)
        inserted.append(f"{item['supplier']} / {item['sku']}")

    await db.commit()
    return {"seeded": len(inserted), "date": today.isoformat(), "items": inserted}

