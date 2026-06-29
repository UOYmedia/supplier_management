import asyncio
import os
import logging
import anthropic
from sqlalchemy import select, or_
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.core.database import AsyncSessionLocal
from app.models.supplier import SupplierProduct

logger = logging.getLogger(__name__)

_PROMPT = (
    "Given this Amazon product listing title, return ONLY a short product name, "
    "2-5 words max. Keep the plant/product name and pot size or height if mentioned. "
    "Drop all marketing words. No punctuation, no explanation.\n"
    "Examples:\n"
    "- 'Jade Plant Live, Crassula Ovata in 2 Inch Pot, Air-Purifying...' -> 'Jade Plant 2inch Pot'\n"
    "- 'Thai Constellation Monstera Plants Live | 4-5 Inch Tall | Decorative...' -> 'Thai Constellation Monstera 4-5inch'\n"
    "- '2 Purple Wisteria Live Plant 12-18in Tall, Fast-Growing...' -> 'Purple Wisteria 12-18inch'\n"
    "- '100 Red Onion Sets, Heirloom, Non-GMO...' -> 'Red Onion Bulbs 100-pack'\n"
    "- 'Goldfish Plant Live | 4 Inch Live Potted Houseplant...' -> 'Goldfish Plant 4inch Pot'\n"
    "Title: {title}"
)

scheduler = AsyncIOScheduler()


async def fill_short_names() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("fill_short_names: ANTHROPIC_API_KEY not set — skipping")
        return

    client = anthropic.AsyncAnthropic(api_key=api_key)
    updated = 0

    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(SupplierProduct)
            .where(or_(SupplierProduct.short_name.is_(None), SupplierProduct.short_name == ""))
            .limit(50)
        )
        products = res.scalars().all()

        if not products:
            logger.info("fill_short_names: nothing to update")
            return

        for sp in products:
            try:
                msg = await client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=50,
                    messages=[{"role": "user", "content": _PROMPT.format(title=sp.name)}],
                )
                sp.short_name = msg.content[0].text.strip()
                await asyncio.sleep(0.5)
                updated += 1
            except Exception as e:
                logger.warning(f"fill_short_names: sp.id={sp.id} failed — {e}")

        await db.commit()

    logger.info(f"fill_short_names: updated {updated} record(s)")


scheduler.add_job(fill_short_names, "interval", hours=1, id="fill_short_names")


# Timezone Amazon uses to record order dates; the daily snapshot's business day
# is cut on this clock so the numbers match what the marketplace shows.
SNAPSHOT_TZ = "America/Los_Angeles"


def _pacific_now():
    from datetime import datetime, timezone, timedelta
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(SNAPSHOT_TZ))
    except Exception:
        # Fallback if the tz database is unavailable: fixed PST offset (no DST).
        return datetime.now(timezone(timedelta(hours=-8)))


async def snapshot_daily_stock(business_date=None):
    """Freeze each active supplier's catalog numbers for one Pacific-time day.

    Idempotent: re-running for a date replaces that date's rows. When
    `business_date` is None we snapshot the day that just ended in Pacific time
    (so the nightly run right after midnight captures the previous full day).
    """
    from datetime import date, timedelta
    from sqlalchemy import select, func, delete
    from app.models.supplier import Supplier, SupplierProduct
    from app.models.order import OrderFulfillmentItem, FulfillStatus
    from app.models.purchase_order import DailyStockSnapshot

    if business_date is None:
        business_date = (_pacific_now() - timedelta(days=1)).date()

    rows = 0
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(DailyStockSnapshot).where(DailyStockSnapshot.business_date == business_date)
        )
        suppliers = (await db.execute(
            select(Supplier).where(Supplier.is_active == True)  # noqa: E712
        )).scalars().all()

        for sup in suppliers:
            products = (await db.execute(
                select(SupplierProduct).where(SupplierProduct.supplier_id == sup.id)
            )).scalars().all()
            for sp in products:
                pending = (await db.execute(
                    select(func.coalesce(func.sum(OrderFulfillmentItem.quantity), 0)).where(
                        OrderFulfillmentItem.supplier_product_id == sp.id,
                        OrderFulfillmentItem.fulfill_status.in_(
                            [FulfillStatus.unfulfilled, FulfillStatus.pending]
                        ),
                    )
                )).scalar()
                available = sp.stock_quantity or 0
                ordered = int(pending or 0)
                oversold = max(0, ordered - available)
                avail_final = max(0, available - ordered)
                unit_cost = sp.unit_price or 0
                db.add(DailyStockSnapshot(
                    business_date=business_date,
                    supplier_id=sup.id,
                    supplier_name=sup.name,
                    sku=sp.sku,
                    product_name=sp.name,
                    available=available,
                    ordered=ordered,
                    oversold=oversold,
                    unit_cost=unit_cost,
                    total_cost=ordered * unit_cost,
                    avail_value=avail_final * unit_cost,
                    oversold_value=oversold * unit_cost,
                ))
                rows += 1
        await db.commit()

    logger.info(f"snapshot_daily_stock: stored {rows} row(s) for {business_date}")
    return business_date, rows


# Run a few minutes after midnight Pacific so the day that just ended is final.
scheduler.add_job(
    snapshot_daily_stock, "cron", hour=0, minute=5,
    timezone=SNAPSHOT_TZ, id="snapshot_daily_stock",
)
