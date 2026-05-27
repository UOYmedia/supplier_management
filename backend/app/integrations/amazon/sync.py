from app.integrations.base import MarketplaceSyncer
from app.integrations.amazon.client import AmazonSPClient
from app.models.marketplace import MarketplaceConnection, MarketplaceListing, ListingStatus
from app.models.product import Product
from app.models.order import Order, OrderLineItem
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

    async def sync_orders(self, db: AsyncSession, created_after: str | None = None) -> int:
        """Fetch unshipped/partially-shipped orders from SP-API with pagination."""
        params: dict = {
            "MarketplaceIds": self.client.marketplace_id,
            "OrderStatuses": "Unshipped,PartiallyShipped",
        }
        if created_after:
            params["CreatedAfter"] = created_after
        elif self.connection.last_synced_at:
            params["LastUpdateAfter"] = self.connection.last_synced_at.isoformat()

        count = 0
        next_token: str | None = None

        while True:
            try:
                if next_token:
                    data = await self.client.get("/orders/v0/orders", params={"NextToken": next_token})
                else:
                    data = await self.client.get("/orders/v0/orders", params=params)
            except Exception:
                break

            payload = data.get("payload", {})
            orders_data = payload.get("Orders", [])
            next_token = payload.get("NextToken")

            for od in orders_data:
                ext_id = od.get("AmazonOrderId")
                existing = await db.execute(select(Order).where(Order.external_order_id == ext_id))
                if existing.scalar_one_or_none():
                    continue

                addr = od.get("ShippingAddress", {})
                order = Order(
                    connection_id=self.connection.id,
                    marketplace="amazon",
                    external_order_id=ext_id,
                    buyer_name=od.get("BuyerInfo", {}).get("BuyerName"),
                    buyer_email=od.get("BuyerInfo", {}).get("BuyerEmail"),
                    shipping_address={
                        "name": addr.get("Name"),
                        "line1": addr.get("AddressLine1"),
                        "line2": addr.get("AddressLine2"),
                        "city": addr.get("City"),
                        "state": addr.get("StateOrRegion"),
                        "zip": addr.get("PostalCode"),
                        "country": addr.get("CountryCode"),
                        "phone": addr.get("Phone"),
                    },
                    total=float(od.get("OrderTotal", {}).get("Amount", 0)),
                    currency=od.get("OrderTotal", {}).get("CurrencyCode", "USD"),
                    ordered_at=datetime.fromisoformat(
                        od.get("PurchaseDate", datetime.now(timezone.utc).isoformat()).replace("Z", "+00:00")
                    ),
                )
                db.add(order)
                await db.flush()

                try:
                    items_data = await self.client.get(f"/orders/v0/orders/{ext_id}/orderItems")
                    for item in items_data.get("payload", {}).get("OrderItems", []):
                        listing = await db.execute(
                            select(MarketplaceListing).where(
                                MarketplaceListing.marketplace_sku == item.get("SellerSKU"),
                                MarketplaceListing.connection_id == self.connection.id,
                            )
                        )
                        listing_obj = listing.scalar_one_or_none()
                        db.add(OrderLineItem(
                            order_id=order.id,
                            product_id=listing_obj.product_id if listing_obj else None,
                            listing_id=listing_obj.id if listing_obj else None,
                            external_line_item_id=item.get("OrderItemId"),   # needed for MFN shipping
                            product_name=item.get("Title", ""),
                            sku=item.get("SellerSKU"),
                            quantity=int(item.get("QuantityOrdered", 1)),
                            price=float(item.get("ItemPrice", {}).get("Amount", 0)),
                        ))
                except Exception:
                    pass

                count += 1

            if not next_token:
                break

        return count

    async def sync_listings(self, db: AsyncSession) -> dict:
        """Pull FBA inventory from Amazon and upsert as MarketplaceListings."""
        created = updated = errors = 0
        next_token: str | None = None

        while True:
            try:
                params: dict = {
                    "details": "true",
                    "granularityType": "Marketplace",
                    "granularityId": self.client.marketplace_id,
                    "marketplaceIds": self.client.marketplace_id,
                }
                if next_token:
                    params = {"nextToken": next_token, "marketplaceIds": self.client.marketplace_id}

                data = await self.client.get("/fba/inventory/v1/summaries", params=params)
            except Exception as e:
                errors += 1
                break

            payload = data.get("payload", {})
            summaries = payload.get("inventorySummaries", [])
            next_token = data.get("pagination", {}).get("nextToken")

            for item in summaries:
                asin = item.get("asin")
                sku = item.get("sellerSku") or item.get("fnSku")
                title = item.get("productName", "")
                qty = item.get("totalQuantity", 0)

                if not sku:
                    continue

                existing_q = await db.execute(
                    select(MarketplaceListing).where(
                        MarketplaceListing.connection_id == self.connection.id,
                        MarketplaceListing.marketplace_sku == sku,
                    )
                )
                listing = existing_q.scalar_one_or_none()

                if listing:
                    listing.external_id = asin
                    listing.title = title
                    listing.status = ListingStatus.active
                    listing.synced_at = datetime.now(timezone.utc)
                    updated += 1
                else:
                    db.add(MarketplaceListing(
                        connection_id=self.connection.id,
                        product_id=None,
                        external_id=asin,
                        marketplace_sku=sku,
                        title=title,
                        status=ListingStatus.active,
                        synced_at=datetime.now(timezone.utc),
                        extra_data={"total_quantity": qty},
                    ))
                    created += 1

            if not next_token:
                break

        return {"created": created, "updated": updated, "errors": errors}

    async def sync_products(self, db: AsyncSession) -> int:
        """Alias for sync_listings (pull from Amazon into local DB)."""
        result = await self.sync_listings(db)
        return result["created"] + result["updated"]
