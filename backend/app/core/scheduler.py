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
