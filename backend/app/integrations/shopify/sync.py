from app.integrations.base import MarketplaceSyncer
from app.integrations.shopify.client import ShopifyClient
from app.models.marketplace import MarketplaceConnection, MarketplaceListing, ListingStatus
from app.models.product import Product
from app.models.order import Order, OrderLineItem
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone


class ShopifySync(MarketplaceSyncer):
    def __init__(self, connection: MarketplaceConnection):
        super().__init__(connection)
        creds = self.credentials
        self.client = ShopifyClient(
            shop_url=connection.shop_url or creds.get("shop_url", ""),
            access_token=creds.get("access_token", ""),
        )

    async def test_connection(self) -> bool:
        try:
            await self.client.get("/shop.json")
            return True
        except Exception:
            return False

    async def push_product(self, product: Product, price: float | None = None) -> str:
        """Create product on Shopify and return product ID."""
        body = {
            "product": {
                "title": product.name,
                "variants": [
                    {
                        "sku": product.sku,
                        "price": str(price or 0),
                        "weight": float(product.weight or 0),
                        "weight_unit": "kg",
                        "inventory_management": "shopify",
                    }
                ],
                "body_html": product.description or "",
            }
        }
        result = await self.client.post("/products.json", body)
        shopify_product = result.get("product", {})
        return str(shopify_product.get("id", ""))

    async def sync_products(self, db: AsyncSession) -> int:
        """Fetch all Shopify products and upsert into local DB as Products + MarketplaceListings."""
        count = 0
        page_info = None

        while True:
            params: dict = {"limit": 250}
            if page_info:
                params["page_info"] = page_info

            try:
                data = await self.client.get("/products.json", params=params)
            except Exception:
                break

            products = data.get("products", [])
            if not products:
                break

            for sp in products:
                # Each Shopify product may have multiple variants — treat each as a SKU
                for variant in sp.get("variants", []):
                    sku = variant.get("sku") or f"SHOPIFY-{sp['id']}-{variant['id']}"
                    external_id = str(sp["id"])

                    # Upsert Product
                    result = await db.execute(
                        select(Product).where(Product.sku == sku)
                    )
                    product = result.scalar_one_or_none()

                    price = float(variant.get("price") or 0)
                    weight = float(variant.get("weight") or 0)
                    title = sp.get("title", "")
                    if len(sp.get("variants", [])) > 1:
                        title = f"{title} - {variant.get('title', '')}"

                    if not product:
                        product = Product(
                            name=title,
                            sku=sku,
                            description=sp.get("body_html", "") or "",
                            weight=weight,
                        )
                        db.add(product)
                        await db.flush()
                    else:
                        product.name = title
                        product.weight = weight

                    # Upsert MarketplaceListing
                    listing_result = await db.execute(
                        select(MarketplaceListing).where(
                            MarketplaceListing.external_id == external_id,
                            MarketplaceListing.connection_id == self.connection.id,
                            MarketplaceListing.marketplace_sku == sku,
                        )
                    )
                    listing = listing_result.scalar_one_or_none()
                    if not listing:
                        db.add(MarketplaceListing(
                            product_id=product.id,
                            connection_id=self.connection.id,
                            external_id=external_id,
                            marketplace_sku=sku,
                            title=title,
                            price=price,
                            status=ListingStatus.active,
                            synced_at=datetime.now(timezone.utc),
                        ))
                    else:
                        listing.title = title
                        listing.price = price
                        listing.synced_at = datetime.now(timezone.utc)

                    count += 1

            # Shopify cursor-based pagination
            # (basic: if fewer than limit returned, we're done)
            if len(products) < 250:
                break

        await db.commit()
        return count

    async def sync_orders(self, db: AsyncSession) -> int:
        """Fetch unfulfilled Shopify orders and upsert into local DB."""
        try:
            data = await self.client.get("/orders.json", params={"fulfillment_status": "unfulfilled", "status": "open", "limit": 250})
        except Exception:
            return 0

        count = 0
        for od in data.get("orders", []):
            ext_id = str(od["id"])
            existing = await db.execute(select(Order).where(Order.external_order_id == ext_id))
            existing_order = existing.scalar_one_or_none()
            if existing_order:
                # Re-link any line items that still have product_id=None
                await self._relink_orphaned_items(existing_order.id, od.get("line_items", []), db)
                continue

            sa = od.get("shipping_address") or {}
            order = Order(
                connection_id=self.connection.id,
                marketplace="shopify",
                external_order_id=ext_id,
                order_name=od.get("name"),
                buyer_name=od.get("customer", {}).get("first_name", "") + " " + od.get("customer", {}).get("last_name", ""),
                buyer_email=od.get("email"),
                shipping_address={
                    "name": sa.get("name"),
                    "line1": sa.get("address1"),
                    "line2": sa.get("address2"),
                    "city": sa.get("city"),
                    "state": sa.get("province"),
                    "zip": sa.get("zip"),
                    "country": sa.get("country_code"),
                    "phone": sa.get("phone"),
                },
                total=float(od.get("total_price", 0)),
                currency=od.get("currency", "USD"),
                ordered_at=datetime.fromisoformat(od.get("created_at", datetime.now(timezone.utc).isoformat())),
            )
            db.add(order)
            await db.flush()

            for item in od.get("line_items", []):
                item_sku = item.get("sku")
                product_id, listing_id = await self._resolve_product(item_sku, db)
                db.add(OrderLineItem(
                    order_id=order.id,
                    product_id=product_id,
                    listing_id=listing_id,
                    external_line_item_id=str(item.get("id")),
                    product_name=item.get("title", ""),
                    sku=item_sku,
                    quantity=item.get("quantity", 1),
                    price=float(item.get("price", 0)),
                ))
            count += 1

        await db.commit()
        return count

    async def _resolve_product(self, sku: str | None, db: AsyncSession) -> tuple[int | None, int | None]:
        """Try to find product_id and listing_id for a given SKU.

        1. Match by MarketplaceListing.marketplace_sku (exact, this connection)
        2. Fallback: match by Product.sku directly
        """
        if not sku:
            return None, None

        listing_res = await db.execute(
            select(MarketplaceListing).where(
                MarketplaceListing.marketplace_sku == sku,
                MarketplaceListing.connection_id == self.connection.id,
            )
        )
        listing_obj = listing_res.scalar_one_or_none()
        if listing_obj:
            return listing_obj.product_id, listing_obj.id

        # Fallback: try matching directly on Product.sku
        prod_res = await db.execute(select(Product).where(Product.sku == sku))
        product = prod_res.scalar_one_or_none()
        if product:
            return product.id, None

        return None, None

    async def _relink_orphaned_items(self, order_id: int, line_items: list, db: AsyncSession) -> None:
        """For an already-synced order, try to fill in product_id for any line items still missing it."""
        li_res = await db.execute(
            select(OrderLineItem).where(
                OrderLineItem.order_id == order_id,
                OrderLineItem.product_id.is_(None),
                OrderLineItem.sku.isnot(None),
            )
        )
        orphans = li_res.scalars().all()
        if not orphans:
            return

        # Build a map of sku -> Shopify line item data for quick lookup
        sku_map = {item.get("sku"): item for item in line_items if item.get("sku")}

        for li in orphans:
            if li.sku not in sku_map:
                continue
            product_id, listing_id = await self._resolve_product(li.sku, db)
            if product_id:
                li.product_id = product_id
            if listing_id:
                li.listing_id = listing_id
