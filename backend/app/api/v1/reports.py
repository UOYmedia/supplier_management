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


@router.get("/supplier-scorecard")
async def supplier_scorecard(
    supplier_id: int = Query(...),
    days: int = Query(30),
    db: AsyncSession = Depends(get_db),
):
    """Operational scorecard for one supplier over a window (read-only):
    order/line/unit counts, total spend (COGS), fulfilment rate, average days
    to ship, open line items, low-stock catalog items, and top products."""
    from fastapi import HTTPException as _HTTPException

    sup = await db.get(Supplier, supplier_id)
    if not sup:
        raise _HTTPException(404, "Supplier not found")

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (await db.execute(
        select(OrderLineItem, Order.ordered_at)
        .join(Order, Order.id == OrderLineItem.order_id)
        .where(OrderLineItem.supplier_id == supplier_id, Order.ordered_at >= cutoff)
    )).all()

    order_ids: set[int] = set()
    units = 0
    total_cogs = 0.0
    status_counts: dict[str, int] = {}
    ship_days: list[float] = []
    prod: dict[str, list[float]] = {}
    for li, ordered_at in rows:
        order_ids.add(li.order_id)
        qty = li.quantity or 0
        units += qty
        cogs = float(li.base_cost or 0) * qty
        total_cogs += cogs
        status_counts[li.fulfill_status] = status_counts.get(li.fulfill_status, 0) + 1
        if li.fulfilled_at and ordered_at and li.fulfill_status in ("shipped", "delivered"):
            ship_days.append((li.fulfilled_at - ordered_at).total_seconds() / 86400)
        name = li.product_name or "Unknown"
        p = prod.setdefault(name, [0, 0.0])
        p[0] += qty
        p[1] += cogs

    line_item_count = len(rows)
    fulfilled = status_counts.get("shipped", 0) + status_counts.get("delivered", 0)
    open_count = status_counts.get("unfulfilled", 0) + status_counts.get("pending", 0)
    low_stock = (await db.execute(
        select(func.count(SupplierProduct.id)).where(
            SupplierProduct.supplier_id == supplier_id,
            SupplierProduct.stock_quantity <= 5,
        )
    )).scalar()
    top_products = sorted(
        ({"name": n, "qty": v[0], "cogs": round(v[1], 2)} for n, v in prod.items()),
        key=lambda x: x["qty"], reverse=True,
    )[:5]

    return {
        "supplier_id": supplier_id,
        "supplier_name": sup.name,
        "days": days,
        "order_count": len(order_ids),
        "line_item_count": line_item_count,
        "units": units,
        "total_cogs": round(total_cogs, 2),
        "fulfilled_count": fulfilled,
        "open_count": open_count,
        "fulfillment_rate": round(fulfilled / line_item_count * 100, 1) if line_item_count else 0,
        "avg_days_to_ship": round(sum(ship_days) / len(ship_days), 1) if ship_days else None,
        "low_stock_count": low_stock,
        "status_counts": status_counts,
        "top_products": top_products,
    }


@router.get("/margin-breakdown")
async def margin_breakdown(
    from_date: datetime | None = Query(None),
    to_date: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Profit detail for the period (read-only). Mirrors /summary totals and
    flags line items with no recorded cost (base_cost = 0) — these inflate
    gross profit/margin, so they're the items to map/cost. Also returns the
    biggest COGS products and the products still missing a cost."""
    oq = select(Order)
    if from_date:
        oq = oq.where(Order.ordered_at >= from_date)
    if to_date:
        oq = oq.where(Order.ordered_at <= to_date)
    orders = (await db.execute(oq)).scalars().all()
    revenue = sum(float(o.total) for o in orders)

    liq = select(OrderLineItem).join(Order, Order.id == OrderLineItem.order_id)
    if from_date:
        liq = liq.where(Order.ordered_at >= from_date)
    if to_date:
        liq = liq.where(Order.ordered_at <= to_date)
    lis = (await db.execute(liq)).scalars().all()

    cost = sum(float(li.base_cost or 0) * (li.quantity or 0) for li in lis)
    gross_profit = revenue - cost
    total_li = len(lis)

    missing_units = 0
    missing_count = 0
    miss_prod: dict[str, int] = {}
    cost_prod: dict[str, float] = {}
    for li in lis:
        qty = li.quantity or 0
        bc = float(li.base_cost or 0)
        name = li.product_name or "Unknown"
        if bc == 0 and qty > 0:
            missing_count += 1
            missing_units += qty
            miss_prod[name] = miss_prod.get(name, 0) + qty
        elif bc > 0:
            cost_prod[name] = cost_prod.get(name, 0.0) + bc * qty

    top_missing = sorted(
        ({"name": n, "units": u} for n, u in miss_prod.items()),
        key=lambda x: x["units"], reverse=True,
    )[:8]
    top_cost_products = sorted(
        ({"name": n, "cogs": round(c, 2)} for n, c in cost_prod.items()),
        key=lambda x: x["cogs"], reverse=True,
    )[:5]

    return {
        "revenue": round(revenue, 2),
        "cost": round(cost, 2),
        "gross_profit": round(gross_profit, 2),
        "margin_pct": round(gross_profit / revenue * 100, 1) if revenue else 0,
        "line_items_total": total_li,
        "missing_cost_count": missing_count,
        "missing_cost_units": missing_units,
        "products_missing_cost": len(miss_prod),
        "cost_coverage_pct": round((total_li - missing_count) / total_li * 100, 1) if total_li else 100,
        "top_missing": top_missing,
        "top_cost_products": top_cost_products,
    }

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
