from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import datetime, timezone, timedelta
from app.core.database import get_db
from app.models.order import Order, OrderLineItem, OrderStatus, OrderFulfillmentItem
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


@router.get("/stock-insights")
async def stock_insights(
    days: int = Query(30, description="velocity window in days"),
    threshold: int = Query(5),
    target_days: int = Query(14, description="desired days of cover for reorder suggestion"),
    db: AsyncSession = Depends(get_db),
):
    """Reorder-planning insight per supplier catalog item (read-only):
    stock vs pending demand, recent sales velocity, projected days of cover,
    and a suggested reorder quantity. Returns only at-risk items (low available
    or running out within target_days), most-urgent first."""
    import math

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Open (pending) demand per catalog item.
    pend_rows = (await db.execute(
        select(
            OrderFulfillmentItem.supplier_product_id,
            func.coalesce(func.sum(OrderFulfillmentItem.quantity), 0),
        )
        .where(OrderFulfillmentItem.fulfill_status.in_(["unfulfilled", "pending"]))
        .group_by(OrderFulfillmentItem.supplier_product_id)
    )).all()
    pending = {spid: int(q or 0) for spid, q in pend_rows}

    # Units demanded within the window → sales velocity.
    sold_rows = (await db.execute(
        select(
            OrderFulfillmentItem.supplier_product_id,
            func.coalesce(func.sum(OrderFulfillmentItem.quantity), 0),
        )
        .join(OrderLineItem, OrderLineItem.id == OrderFulfillmentItem.order_line_item_id)
        .join(Order, Order.id == OrderLineItem.order_id)
        .where(Order.ordered_at >= cutoff)
        .group_by(OrderFulfillmentItem.supplier_product_id)
    )).all()
    sold = {spid: int(q or 0) for spid, q in sold_rows}

    sp_rows = (await db.execute(
        select(
            SupplierProduct.id, SupplierProduct.name, SupplierProduct.short_name,
            SupplierProduct.sku, SupplierProduct.stock_quantity,
            SupplierProduct.supplier_id, Supplier.name,
        )
        .join(Supplier, Supplier.id == SupplierProduct.supplier_id)
    )).all()

    items = []
    for spid, name, short_name, sku, stock, sup_id, sup_name in sp_rows:
        stock = int(stock or 0)
        pend = pending.get(spid, 0)
        available = stock - pend
        sold_window = sold.get(spid, 0)
        velocity = (sold_window / days) if days else 0.0
        days_cover = (available / velocity) if velocity > 0 else None

        reorder = 0
        if velocity > 0:
            reorder = max(0, math.ceil(velocity * target_days) - available)
        elif available < 0:
            reorder = -available

        at_risk = (available <= threshold) or (days_cover is not None and days_cover <= target_days)
        if not at_risk:
            continue
        items.append({
            "supplier_product_id": spid,
            "name": short_name or name,
            "sku": sku,
            "supplier_id": sup_id,
            "supplier_name": sup_name,
            "stock": stock,
            "pending": pend,
            "available": available,
            "sold_window": sold_window,
            "velocity_per_day": round(velocity, 2),
            "days_of_cover": round(days_cover, 1) if days_cover is not None else None,
            "suggested_reorder": int(reorder),
        })

    items.sort(key=lambda x: (
        x["days_of_cover"] if x["days_of_cover"] is not None else float("inf"),
        x["available"],
    ))
    return {"days": days, "target_days": target_days, "count": len(items), "items": items}

from decimal import Decimal
from datetime import date as Date
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.models.daily_balance import DailyBalance


class DailyBalanceIn(BaseModel):
    date: Date
    ending_balance: Decimal
    top_up: Decimal = Decimal(0)
    external_cogs: Decimal = Decimal(0)


class DailyBalanceOut(BaseModel):
    date: Date
    ending_balance: Decimal
    top_up: Decimal = Decimal(0)
    external_cogs: Decimal = Decimal(0)


@router.get("/daily-balance", response_model=DailyBalanceOut | None)
async def get_daily_balance(date: Date = Query(...), db: AsyncSession = Depends(get_db)):
    """Return the stored ending balance + manual top-up + external COGS for a date, or null."""
    row = (await db.execute(select(DailyBalance).where(DailyBalance.date == date))).scalar_one_or_none()
    if not row:
        return None
    return DailyBalanceOut(
        date=row.date,
        ending_balance=row.ending_balance,
        top_up=row.top_up or Decimal(0),
        external_cogs=getattr(row, "external_cogs", None) or Decimal(0),
    )


@router.post("/daily-balance", response_model=DailyBalanceOut)
async def upsert_daily_balance(body: DailyBalanceIn, db: AsyncSession = Depends(get_db)):
    """Save (upsert) ending balance + manual top-up + external COGS for a date."""
    stmt = (
        pg_insert(DailyBalance)
        .values(
            date=body.date,
            ending_balance=body.ending_balance,
            top_up=body.top_up,
            external_cogs=body.external_cogs,
        )
        .on_conflict_do_update(
            index_elements=["date"],
            set_={
                "ending_balance": body.ending_balance,
                "top_up": body.top_up,
                "external_cogs": body.external_cogs,
            },
        )
    )
    await db.execute(stmt)
    await db.commit()
    return DailyBalanceOut(
        date=body.date,
        ending_balance=body.ending_balance,
        top_up=body.top_up,
        external_cogs=body.external_cogs,
    )
