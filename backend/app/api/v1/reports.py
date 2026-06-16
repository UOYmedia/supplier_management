from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import datetime, timezone
from app.core.database import get_db
from app.models.order import Order, OrderLineItem, OrderStatus
from app.models.product import Product, ProductSupplier, ProductComponent
from app.models.supplier import Supplier, SupplierProduct

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/summary")
async def business_summary(
    from_date: datetime | None = Query(None),
    to_date: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = select(Order)
    if from_date:
        q = q.where(Order.ordered_at >= from_date)
    if to_date:
        q = q.where(Order.ordered_at <= to_date)
    result = await db.execute(q)
    orders = result.scalars().all()

    total_revenue = sum(float(o.total) for o in orders)
    order_count = len(orders)

    li_q = select(OrderLineItem).join(Order, Order.id == OrderLineItem.order_id)
    if from_date:
        li_q = li_q.where(Order.ordered_at >= from_date)
    if to_date:
        li_q = li_q.where(Order.ordered_at <= to_date)
    li_result = await db.execute(li_q)
    line_items = li_result.scalars().all()

    total_cost = sum(float(li.base_cost) * li.quantity for li in line_items)
    gross_profit = total_revenue - total_cost

    return {
        "order_count": order_count,
        "total_revenue": round(total_revenue, 2),
        "total_cost": round(total_cost, 2),
        "gross_profit": round(gross_profit, 2),
        "margin_pct": round(gross_profit / total_revenue * 100, 1) if total_revenue else 0,
    }


@router.get("/by-marketplace")
async def revenue_by_marketplace(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Order.marketplace, func.count(Order.id), func.sum(Order.total))
        .group_by(Order.marketplace)
    )
    rows = result.all()
    return [{"marketplace": r[0], "order_count": r[1], "revenue": float(r[2] or 0)} for r in rows]


@router.get("/by-supplier")
async def revenue_by_supplier(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(
            Supplier.id, Supplier.name,
            func.count(OrderLineItem.id),
            func.sum(OrderLineItem.base_cost * OrderLineItem.quantity),
        )
        .join(OrderLineItem, OrderLineItem.supplier_id == Supplier.id)
        .group_by(Supplier.id, Supplier.name)
    )
    rows = result.all()
    return [
        {"supplier_id": r[0], "supplier_name": r[1], "line_item_count": r[2], "total_cost": float(r[3] or 0)}
        for r in rows
    ]


@router.get("/inventory-alert")
async def inventory_alert(threshold: int = Query(5), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ProductSupplier, Product, Supplier)
        .join(Product, Product.id == ProductSupplier.product_id)
        .join(Supplier, Supplier.id == ProductSupplier.supplier_id)
        .where(ProductSupplier.stock <= threshold)
    )
    rows = result.all()

    output = []
    for ps, product, supplier in rows:
        sp_res = await db.execute(
            select(SupplierProduct)
            .join(ProductComponent, ProductComponent.supplier_product_id == SupplierProduct.id)
            .where(
                ProductComponent.product_id == product.id,
                SupplierProduct.supplier_id == supplier.id,
            )
            .limit(1)
        )
        sp = sp_res.scalar_one_or_none()
        display_name = (sp.short_name or sp.name) if sp else product.name

        output.append({
            "product_id": product.id,
            "product_name": product.name,
            "display_name": display_name,
            "sku": product.sku,
            "supplier_id": supplier.id,
            "supplier_name": supplier.name,
            "stock": ps.stock,
        })

    return output


# ── Daily balance endpoints ──────────────────────────────────────────────────

from decimal import Decimal
from datetime import date as Date
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.models.daily_balance import DailyBalance


class DailyBalanceIn(BaseModel):
    date: Date
    ending_balance: Decimal


class DailyBalanceOut(BaseModel):
    date: Date
    ending_balance: Decimal


@router.get("/daily-balance", response_model=DailyBalanceOut | None)
async def get_daily_balance(date: Date = Query(...), db: AsyncSession = Depends(get_db)):
    """Return the stored ending balance for a given date, or null if none."""
    row = (await db.execute(select(DailyBalance).where(DailyBalance.date == date))).scalar_one_or_none()
    if not row:
        return None
    return DailyBalanceOut(date=row.date, ending_balance=row.ending_balance)


@router.post("/daily-balance", response_model=DailyBalanceOut)
async def upsert_daily_balance(body: DailyBalanceIn, db: AsyncSession = Depends(get_db)):
    """Save (upsert) ending balance for a date."""
    stmt = (
        pg_insert(DailyBalance)
        .values(date=body.date, ending_balance=body.ending_balance)
        .on_conflict_do_update(
            index_elements=["date"],
            set_={"ending_balance": body.ending_balance},
        )
    )
    await db.execute(stmt)
    await db.commit()
    return DailyBalanceOut(date=body.date, ending_balance=body.ending_balance)
