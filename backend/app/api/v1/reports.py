from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import datetime, timezone
from app.core.database import get_db
from app.models.order import Order, OrderLineItem, OrderStatus
from app.models.product import Product, ProductSupplier
from app.models.supplier import Supplier

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

    li_q = select(OrderLineItem)
    if from_date or to_date:
        li_q = li_q.join(Order).where(q.whereclause) if q.whereclause is not None else li_q
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
    return [
        {
            "product_id": r[1].id,
            "product_name": r[1].name,
            "sku": r[1].sku,
            "supplier_id": r[2].id,
            "supplier_name": r[2].name,
            "stock": r[0].stock,
        }
        for r in rows
    ]
