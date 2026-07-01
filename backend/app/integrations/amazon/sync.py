from app.integrations.base import MarketplaceSyncer
from app.integrations.amazon.client import AmazonSPClient
from app.models.marketplace import MarketplaceConnection
from app.models.product import Product
from app.models.order import Order, OrderLineItem
from app.models.marketplace import MarketplaceListing
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone


class AmazonSync(MarketplaceSyncer):
    def __init__(self, connection: MarketplaceConnection):
        super().__init__(connection)
        creds = self.credentials
        self.client = AmazonSPClient(
            client_id=creds.get("client_id", ""),
            client_secret=creds.get("client_secret", ""),
            refresh_token=creds.get("refresh_token", ""),
            marketplace_id=connection.marketplace_id or "ATVPDKIKX0DER",
        )

    async def test_connection(self) -> bool:
        try:
            await self.client.get("/sellers/v1/marketplaceParticipations")
            return True
        except Exception:
            return False

    async def push_product(self, product: Product, price: float | None = None) -> str:
        """Create/update a listing on Amazon. Returns ASIN or seller SKU."""
        body = {
            "productType": "PRODUCT",
            "attributes": {
                "item_name": [{"value": product.name, "marketplace_id": self.client.marketplace_id}],
                "merchant_suggested_asin": [],
                "fulfillment_availability": [{"fulfillment_channel_code": "DEFAULT"}],
            },
        }
        if price:
            body["attributes"]["list_price"] = [{"value": price, "currency": "USD"}]

        result = await self.client.post(
            f"/listings/2021-08-01/items/{product.sku}/{product.sku}",
            body,
        )
        return result.get("sku", product.sku)

    async def _fetch_address(self, order_id: str) -> dict | None:
        """SP-API hides shipping address by default. Try direct GET first
        (works if seller account has shippingAddress access), fall back to
        Restricted Data Token flow. Returns None if seller account isn't
        authorised for PII."""
        path = f"/orders/v0/orders/{order_id}/address"
        try:
            data = await self.client.get(path)
            addr = (data.get("payload") or {}).get("ShippingAddress")
            if addr:
                print(f"Amazon address (direct) OK for {order_id}", flush=True)
                return addr
            print(f"Amazon address (direct) returned empty payload for {order_id}", flush=True)
        except Exception as e:
            print(f"Amazon address (direct) failed for {order_id}: {e}", flush=True)
        rdt = await self.client.create_restricted_data_token(
            path=path, method="GET", data_elements=["shippingAddress"]
        )
        if not rdt:
            print(f"Amazon address: no RDT granted for {order_id} — seller likely missing Direct-to-Consumer Shipping role", flush=True)
            return None
        try:
            data = await self.client.get(path, rdt=rdt)
            addr = (data.get("payload") or {}).get("ShippingAddress")
            print(f"Amazon address (RDT) OK for {order_id}: keys={list(addr.keys()) if addr else None}", flush=True)
            return addr
        except Exception as e:
            print(f"Amazon address (RDT) call failed for {order_id}: {e}", flush=True)
            return None

    async def _fetch_buyer_info(self, order_id: str) -> dict | None:
        """Same PII gate as the address endpoint."""
        path = f"/orders/v0/orders/{order_id}/buyerInfo"
        try:
            data = await self.client.get(path)
            info = data.get("payload")
            if info and (info.get("BuyerName") or info.get("BuyerEmail")):
                print(f"Amazon buyer info (direct) OK for {order_id}", flush=True)
                return info
            print(f"Amazon buyer info (direct) returned empty payload for {order_id}", flush=True)
        except Exception as e:
            print(f"Amazon buyer info (direct) failed for {order_id}: {e}", flush=True)
        rdt = await self.client.create_restricted_data_token(
            path=path, method="GET", data_elements=["buyerInfo"]
        )
        if not rdt:
            print(f"Amazon buyer info: no RDT granted for {order_id}", flush=True)
            return None
        try:
            data = await self.client.get(path, rdt=rdt)
            info = data.get("payload")
            print(f"Amazon buyer info (RDT) OK for {order_id}: name={bool(info and info.get('BuyerName'))}, email={bool(info and info.get('BuyerEmail'))}", flush=True)
            return info
        except Exception as e:
            print(f"Amazon buyer info (RDT) call failed for {order_id}: {e}", flush=True)
            return None

    async def sync_orders(
        self,
        db: AsyncSession,
        created_after: str | None = None,
        force_refresh: bool = False,
    ) -> int:
        """Fetch unshipped orders from SP-API and upsert into local DB.

        SP-API /orders/v0/orders REQUIRES one of CreatedAfter / CreatedBefore /
        LastUpdatedAfter / LastUpdatedBefore / NextToken — otherwise it
        responds 400 'InvalidInput'. We default CreatedAfter to 30 days back
        when the caller doesn't pass one. Exceptions propagate so the
        background task records the real error on the connection instead of
        silently returning 0.

        force_refresh=True re-fetches PII (address, buyer info, ASIN) for
        orders that already exist locally — useful after granting
        Direct-to-Consumer Shipping role or fixing the sync code.
        """
        from datetime import timedelta
        if not created_after:
            created_after = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

        params: dict = {
            "MarketplaceIds": self.client.marketplace_id,
            "OrderStatuses": "Unshipped,PartiallyShipped",
            "CreatedAfter": created_after,
        }

        data = await self.client.get("/orders/v0/orders", params=params)
        orders_data = data.get("payload", {}).get("Orders", []) or []
        next_token = data.get("payload", {}).get("NextToken")

        # Paginate
        all_orders = list(orders_data)
        while next_token:
            try:
                page = await self.client.get("/orders/v0/orders", params={
                    "MarketplaceIds": self.client.marketplace_id,
                    "NextToken": next_token,
                })
            except Exception as e:
                print(f"Amazon sync_orders: pagination stopped — {e}", flush=True)
                break
            all_orders.extend(page.get("payload", {}).get("Orders", []) or [])
            next_token = page.get("payload", {}).get("NextToken")

        print(f"Amazon sync_orders: fetched {len(all_orders)} orders (CreatedAfter={created_after})", flush=True)

        count = 0
        refreshed = 0
        for od in all_orders:
            ext_id = od.get("AmazonOrderId")
            if not ext_id:
                continue
            existing_q = await db.execute(select(Order).where(Order.external_order_id == ext_id))
            existing_order = existing_q.scalar_one_or_none()

            if existing_order and not force_refresh:
                continue

            if existing_order and force_refresh:
                # Update PII + ASIN on an order we already imported
                addr = await self._fetch_address(ext_id)
                buyer_info = await self._fetch_buyer_info(ext_id) or {}
                changes: list[str] = []
                if addr:
                    new_addr = {
                        "name": addr.get("Name"),
                        "line1": addr.get("AddressLine1"),
                        "line2": addr.get("AddressLine2"),
                        "city": addr.get("City"),
                        "state": addr.get("StateOrRegion"),
                        "zip": addr.get("PostalCode"),
                        "country": addr.get("CountryCode"),
                        "phone": addr.get("Phone"),
                    }
                    existing_order.shipping_address = new_addr
                    # JSON columns aren't always dirty-tracked on in-place assignment;
                    # flag_modified ensures the UPDATE actually fires.
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(existing_order, "shipping_address")
                    changes.append(f"address(line1={new_addr.get('line1')!r})")
                if buyer_info.get("BuyerName"):
                    existing_order.buyer_name = buyer_info.get("BuyerName")
                    changes.append("buyer_name")
                if buyer_info.get("BuyerEmail"):
                    existing_order.buyer_email = buyer_info.get("BuyerEmail")
                    changes.append("buyer_email")
                # Also backfill ASIN on existing line items
                asin_updated = 0
                try:
                    items_data = await self.client.get(f"/orders/v0/orders/{ext_id}/orderItems")
                    asin_by_sku = {
                        it.get("SellerSKU"): it.get("ASIN")
                        for it in items_data.get("payload", {}).get("OrderItems", [])
                        if it.get("ASIN")
                    }
                    li_q = await db.execute(select(OrderLineItem).where(OrderLineItem.order_id == existing_order.id))
                    for li in li_q.scalars().all():
                        if not li.asin and li.sku and asin_by_sku.get(li.sku):
                            li.asin = asin_by_sku[li.sku]
                            asin_updated += 1
                except Exception as e:
                    print(f"Amazon sync_orders: ASIN backfill failed for {ext_id} — {e}", flush=True)
                if asin_updated:
                    changes.append(f"asin×{asin_updated}")
                await db.commit()
                if changes:
                    print(f"Amazon refresh OK ext_id={ext_id} local_id={existing_order.id}: {', '.join(changes)}", flush=True)
                else:
                    print(f"Amazon refresh: no changes applied for ext_id={ext_id} local_id={existing_order.id}", flush=True)
                refreshed += 1
                continue

            order_total = od.get("OrderTotal") or {}
            try:
                ordered_at = datetime.fromisoformat(od.get("PurchaseDate", "").replace("Z", "+00:00"))
            except Exception:
                ordered_at = datetime.now(timezone.utc)

            # SP-API hides shipping address + buyer info by default — they live
            # behind PII endpoints that need a Restricted Data Token. Try each;
            # fall back to whatever (if anything) was inlined on the order.
            addr = await self._fetch_address(ext_id) or (od.get("ShippingAddress") or {})
            buyer_info = await self._fetch_buyer_info(ext_id) or (od.get("BuyerInfo") or {})

            order = Order(
                connection_id=self.connection.id,
                marketplace="amazon",
                external_order_id=ext_id,
                buyer_name=buyer_info.get("BuyerName"),
                buyer_email=buyer_info.get("BuyerEmail"),
                shipping_address={
                    "name": addr.get("Name"),
                    "line1": addr.get("AddressLine1"),
                    "line2": addr.get("AddressLine2"),
                    "city": addr.get("City"),
                    "state": addr.get("StateOrRegion"),
                    "zip": addr.get("PostalCode"),
                    "country": addr.get("CountryCode"),
                    "phone": addr.get("Phone"),
                } if addr else None,
                total=float(order_total.get("Amount", 0)),
                currency=order_total.get("CurrencyCode", "USD"),
                ordered_at=ordered_at,
            )
            db.add(order)
            await db.flush()

            # fetch line items — error per order shouldn't kill the batch
            line_items: list[OrderLineItem] = []
            try:
                items_data = await self.client.get(f"/orders/v0/orders/{ext_id}/orderItems")
                for item in items_data.get("payload", {}).get("OrderItems", []):
                    # A SKU may (wrongly) map to more than one listing on the same
                    # connection — there's no DB uniqueness guard — so take the
                    # earliest match instead of scalar_one_or_none(), which would
                    # raise MultipleResultsFound and abort the whole sync.
                    listing = await db.execute(
                        select(MarketplaceListing).where(
                            MarketplaceListing.marketplace_sku == item.get("SellerSKU"),
                            MarketplaceListing.connection_id == self.connection.id,
                        ).order_by(MarketplaceListing.id).limit(1)
                    )
                    listing_obj = listing.scalars().first()
                    li = OrderLineItem(
                        order_id=order.id,
                        product_id=listing_obj.product_id if listing_obj else None,
                        listing_id=listing_obj.id if listing_obj else None,
                        external_line_item_id=item.get("OrderItemId"),
                        product_name=item.get("Title", ""),
                        sku=item.get("SellerSKU"),
                        asin=item.get("ASIN"),
                        quantity=int(item.get("QuantityOrdered", 1)),
                        price=float((item.get("ItemPrice") or {}).get("Amount", 0)),
                    )
                    db.add(li)
                    line_items.append(li)
                await db.flush()
            except Exception as e:
                print(f"Amazon sync_orders: line items fetch failed for {ext_id} — {e}", flush=True)

            # Auto-expand ProductComponents into OrderFulfillmentItems for combos
            try:
                from app.integrations.fulfillment_helper import create_fulfillment_items_for_line_item
                for li in line_items:
                    await create_fulfillment_items_for_line_item(db, li)
            except Exception as e:
                print(f"Amazon sync_orders: fulfillment expansion failed for {ext_id} — {e}", flush=True)

            # Auto-assign supplier_id via SKU → Product → ProductComponent
            try:
                from app.api.v1.orders import _auto_assign_line_item
                for li in line_items:
                    await _auto_assign_line_item(li, db)
            except Exception as e:
                print(f"Amazon sync_orders: auto-assign failed for {ext_id} — {e}", flush=True)

            await db.commit()  # commit per order so a later failure doesn't lose progress
            count += 1

        print(f"Amazon sync_orders: imported {count} new orders, refreshed {refreshed} existing", flush=True)
        return count + refreshed
