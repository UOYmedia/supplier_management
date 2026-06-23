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
from app.schemas.purchase_order import (
    BalanceOut,
    POCreate,
    PODailyResponse,
    PORead,
    POStatusUpdate,
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

    if gap > 3:
        status = "ok"
    elif gap > 0:
        status = "low"
    elif gap == 0:
        status = "exact"
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
        .where(PurchaseOrder.created_date == ref_date)
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


# ── GET /balance/today ────────────────────────────────────────────────────────

@router.get("/balance/today", response_model=BalanceOut)
async def get_today_balance(db: AsyncSession = Depends(get_db)):
    today = date.today()
    starting_balance = await _get_starting_balance(db, today)

    result = await db.execute(
        select(PurchaseOrder).where(PurchaseOrder.created_date == today)
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

