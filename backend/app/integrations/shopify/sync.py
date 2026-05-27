from app.integrations.base import MarketplaceSyncer
from app.integrations.shopify.client import ShopifyClient
from app.models.marketplace import MarketplaceConnection, MarketplaceListing, ListingStatus
from app.models.product import Product
from app.models.order import Order, OrderLineItem
from app.models.supplier import Supplier
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
                            marketplace="shopify",
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

    async def sync_locations(self, db: AsyncSession) -> dict:
        """
        Pull Shopify locations and upsert as Suppliers.
        Returns {"created": n, "updated": n, "locations": [...]}
        """
        locations = await self.client.get_locations()
        created = updated = 0
        synced = []

        for loc in locations:
            if not loc.get("active"):
                continue

            location_id = str(loc["id"])
            result = await db.execute(
                select(Supplier).where(Supplier.shopify_location_id == location_id)
            )
            supplier = result.scalar_one_or_none()

            addr1 = loc.get("address1") or ""
            addr2 = loc.get("address2") or ""
            city = loc.get("city") or ""
            state = loc.get("province") or ""
            country = loc.get("country_code") or loc.get("country") or ""
            zipcode = loc.get("zip") or ""
            phone = loc.get("phone") or ""

            if supplier:
                supplier.name = loc["name"]
                supplier.street1 = addr1
                supplier.street2 = addr2
                supplier.city = city
                supplier.state = state
                supplier.country = country
                supplier.zipcode = zipcode
                supplier.phone = phone
                updated += 1
            else:
                supplier = Supplier(
                    name=loc["name"],
                    street1=addr1,
                    street2=addr2,
                    city=city,
                    state=state,
                    country=country,
                    zipcode=zipcode,
                    phone=phone,
                    shopify_location_id=location_id,
                    is_active=True,
                )
                db.add(supplier)
                await db.flush()
                created += 1

            synced.append({
                "shopify_location_id": location_id,
                "name": loc["name"],
                "supplier_id": supplier.id,
                "action": "updated" if updated and not created else "created",
            })

        await db.commit()
        return {"created": created, "updated": updated, "locations": synced}

    async def sync_orders(self, db: AsyncSession) -> int:
        """Fetch unfulfilled Shopify orders and upsert into local DB.
        Uses fulfillment_orders API to auto-assign suppliers by Shopify location."""
        try:
            data = await self.client.get("/orders.json", params={"fulfillment_status": "unfulfilled", "status": "open", "limit": 250})
        except Exception:
            return 0

        # Pre-load location_id → supplier_id map for this sync run
        location_supplier_map = await self._load_location_supplier_map(db)

        count = 0
        for od in data.get("orders", []):
            ext_id = str(od["id"])
            existing = await db.execute(select(Order).where(Order.external_order_id == ext_id))
            if existing.scalar_one_or_none():
                continue

            sa = od.get("shipping_address") or {}
            order = Order(
                connection_id=self.connection.id,
                marketplace="shopify",
                external_order_id=ext_id,
                buyer_name=(
                    (od.get("customer") or {}).get("first_name", "")
                    + " "
                    + (od.get("customer") or {}).get("last_name", "")
                ).strip(),
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

            # Build map: shopify line_item_id → OrderLineItem for location assignment
            li_by_shopify_id: dict[str, OrderLineItem] = {}
            for item in od.get("line_items", []):
                listing_res = await db.execute(
                    select(MarketplaceListing).where(
                        MarketplaceListing.marketplace_sku == item.get("sku"),
                        MarketplaceListing.connection_id == self.connection.id,
                    )
                )
                listing_obj = listing_res.scalar_one_or_none()
                shopify_li_id = str(item.get("id"))
                li = OrderLineItem(
                    order_id=order.id,
                    product_id=listing_obj.product_id if listing_obj else None,
                    listing_id=listing_obj.id if listing_obj else None,
                    external_line_item_id=shopify_li_id,
                    product_name=item.get("title", ""),
                    sku=item.get("sku"),
                    quantity=item.get("quantity", 1),
                    price=float(item.get("price", 0)),
                )
                db.add(li)
                li_by_shopify_id[shopify_li_id] = li

            await db.flush()

            # Create fulfillment items for products with components
            from app.integrations.fulfillment_helper import create_fulfillment_items_for_line_item
            for li in li_by_shopify_id.values():
                await create_fulfillment_items_for_line_item(db, li)

            # Assign suppliers via fulfillment_orders (best effort — skip on error)
            if location_supplier_map:
                await self._assign_suppliers_from_fulfillment_orders(
                    ext_id, li_by_shopify_id, location_supplier_map
                )

            count += 1

        await db.commit()
        return count

    async def _load_location_supplier_map(self, db: AsyncSession) -> dict[str, int]:
        """Returns {shopify_location_id: supplier_id} for all linked suppliers."""
        result = await db.execute(
            select(Supplier).where(Supplier.shopify_location_id.isnot(None))
        )
        return {
            s.shopify_location_id: s.id
            for s in result.scalars().all()
            if s.shopify_location_id
        }

    async def _assign_suppliers_from_fulfillment_orders(
        self,
        shopify_order_id: str,
        li_by_shopify_id: dict[str, "OrderLineItem"],
        location_map: dict[str, int],
    ) -> None:
        """Map fulfillment order locations → line item supplier_id."""
        try:
            fulfillment_orders = await self.client.get_fulfillment_orders(shopify_order_id)
        except Exception:
            return

        for fo in fulfillment_orders:
            location_id = str(fo.get("assigned_location_id", ""))
            supplier_id = location_map.get(location_id)
            if not supplier_id:
                continue
            for fo_item in fo.get("line_items", []):
                shopify_li_id = str(fo_item.get("line_item_id", ""))
                li = li_by_shopify_id.get(shopify_li_id)
                if li:
                    li.supplier_id = supplier_id
