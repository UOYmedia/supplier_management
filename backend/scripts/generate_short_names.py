"""
Generate short names for SupplierProduct records using Claude Haiku.

Usage:
  python scripts/generate_short_names.py
  python scripts/generate_short_names.py --dry-run
"""
import asyncio
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anthropic
from sqlalchemy import select, or_
from app.core.database import AsyncSessionLocal
from app.models.supplier import SupplierProduct

PROMPT_TEMPLATE = (
    "Shorten this Amazon product title for a shipping label.\n"
    "Max 35 characters. Keep: quantity size/pot info.\n"
    "Remove: marketing words, punctuation, pipe symbols.\n"
    "Return ONLY the short name, nothing else.\n"
    "Title: {title}"
)


def generate_short_name(client: anthropic.Anthropic, title: str) -> str:
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=64,
        messages=[{"role": "user", "content": PROMPT_TEMPLATE.format(title=title)}],
    )
    for block in response.content:
        if block.type == "text":
            return block.text.strip()[:35]
    return title[:35]


async def main(dry_run: bool) -> None:
    client = anthropic.Anthropic()

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(SupplierProduct).where(
                or_(
                    SupplierProduct.short_name.is_(None),
                    SupplierProduct.short_name == "",
                )
            )
        )
        products = result.scalars().all()

    print(f"Found {len(products)} product(s) without short_name.", flush=True)
    if not products:
        return

    updated = 0
    async with AsyncSessionLocal() as db:
        for sp in products:
            title = sp.name or ""
            if not title.strip():
                print(f"  Skipping id={sp.id} (empty name)", flush=True)
                continue

            short_name = generate_short_name(client, title)
            print(f"  {'[DRY RUN] Would update' if dry_run else 'Updated'}: {title!r} → {short_name!r}", flush=True)

            if not dry_run:
                sp_db = await db.get(SupplierProduct, sp.id)
                if sp_db is not None:
                    sp_db.short_name = short_name
                    updated += 1

        if not dry_run:
            await db.commit()

    if not dry_run:
        print(f"Done. {updated} record(s) updated.", flush=True)
    else:
        print(f"Dry run complete. {len(products)} record(s) would be updated.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate short names for SupplierProduct records.")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing to DB.")
    args = parser.parse_args()

    asyncio.run(main(dry_run=args.dry_run))
