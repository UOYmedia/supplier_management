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

    async def sync_orders(self, db: AsyncSession) -> int:
        """Fetch unshipped orders from SP-API and upsert into local DB."""
        try:
            data = await self.client.get("/orders/v0/orders", params={
                "MarketplaceIds": self.client.marketplace_id,
                "OrderStatuses": "Unshipped,PartiallyShipped",
            })
        except Exception:
            return 0

        orders_data = data.get("payload", {}).get("Orders", [])
        count = 0
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
                },
                total=float(od.get("OrderTotal", {}).get("Amount", 0)),
                currency=od.get("OrderTotal", {}).get("CurrencyCode", "USD"),
                ordered_at=datetime.fromisoformat(od.get("PurchaseDate", datetime.now(timezone.utc).isoformat())),
            )
            db.add(order)
            await db.flush()

            # fetch line items
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
                        external_line_item_id=item.get("OrderItemId"),
                        product_name=item.get("Title", ""),
                        sku=item.get("SellerSKU"),
                        quantity=int(item.get("QuantityOrdered", 1)),
                        price=float(item.get("ItemPrice", {}).get("Amount", 0)),
                    ))
            except Exception:
                pass

            count += 1

        return count
