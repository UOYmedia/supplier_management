"""
Seed purchase orders for today to match the original sample data layout.

Usage (from backend/ directory):
  python app/seeds/purchase_orders_seed.py

Sample data mirrors the hardcoded frontend RAW_ITEMS so the UI shows the
same oversold/gap pattern after switching to live data.
"""
import asyncio
import sys
import os
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import select, delete
from app.core.database import AsyncSessionLocal
from app.models.purchase_order import PurchaseOrder
import app.models  # noqa: F401 — ensures all models are registered


# qty_available mirrors original sample "available" column so gap/oversold match
SEED_ITEMS = [
    # JOE — Baby Breath & Crown of Thorn oversold (available < ordered)
    {"supplier": "JOE",   "sku": "Meyer Lemon Tree",       "qty_ordered": 5,  "qty_available": 8,  "unit_cost": 15.00},
    {"supplier": "JOE",   "sku": "Baby Breath",            "qty_ordered": 6,  "qty_available": 4,  "unit_cost": 5.00 },
    {"supplier": "JOE",   "sku": "Crown of Thorn Red",     "qty_ordered": 10, "qty_available": 7,  "unit_cost": 7.50 },
    {"supplier": "JOE",   "sku": "French Tarragon",        "qty_ordered": 4,  "qty_available": 12, "unit_cost": 5.00 },
    # SKY — Spanish Lavender & Night Blooming Jasmine exact, Rasp Buddleia oversold
    {"supplier": "SKY",   "sku": "Spanish Lavender",       "qty_ordered": 8,  "qty_available": 8,  "unit_cost": 5.00 },
    {"supplier": "SKY",   "sku": "English Lavender",       "qty_ordered": 4,  "qty_available": 10, "unit_cost": 5.00 },
    {"supplier": "SKY",   "sku": "Night Blooming Jasmine", "qty_ordered": 6,  "qty_available": 6,  "unit_cost": 6.50 },
    {"supplier": "SKY",   "sku": "Rasp Buddleia",          "qty_ordered": 5,  "qty_available": 3,  "unit_cost": 6.50 },
    # FAIRY — all within stock
    {"supplier": "FAIRY", "sku": "Peppermint",             "qty_ordered": 3,  "qty_available": 5,  "unit_cost": 5.00 },
    {"supplier": "FAIRY", "sku": "Confederate Jasmine",    "qty_ordered": 7,  "qty_available": 7,  "unit_cost": 6.50 },
    {"supplier": "FAIRY", "sku": "Thai Constellation",     "qty_ordered": 2,  "qty_available": 4,  "unit_cost": 13.50},
]

PO_NUMBERS = {
    "JOE":   "PO-2026-0623-JOE",
    "SKY":   "PO-2026-0623-SKY",
    "FAIRY": "PO-2026-0623-FAIRY",
}


async def seed():
    today = date.today()
    async with AsyncSessionLocal() as db:
        # Clear existing POs for today to allow re-running safely
        await db.execute(
            delete(PurchaseOrder).where(PurchaseOrder.created_date == today)
        )
        await db.commit()

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

        await db.commit()
        print(f"Seeded {len(SEED_ITEMS)} purchase orders for {today}", flush=True)

        # Verify
        result = await db.execute(
            select(PurchaseOrder).where(PurchaseOrder.created_date == today)
        )
        rows = result.scalars().all()
        print(f"Confirmed {len(rows)} rows in purchase_orders:", flush=True)
        for r in rows:
            gap = r.qty_available - r.qty_ordered
            print(
                f"  {r.supplier:5} | {r.sku:25} | ordered={r.qty_ordered} "
                f"available={r.qty_available} gap={gap:+d} | {r.status}",
                flush=True,
            )


if __name__ == "__main__":
    asyncio.run(seed())
