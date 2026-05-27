from datetime import datetime, timezone
from app.integrations.amazon.client import AmazonSPClient


class AmazonFulfillment:
    def __init__(self, client: AmazonSPClient):
        self.client = client

    async def confirm_shipment(
        self,
        amazon_order_id: str,
        order_item_id: str,
        quantity: int,
        tracking_number: str,
        carrier_code: str = "Other",
    ) -> None:
        """Confirm shipment of an order item to Amazon SP-API."""
        body = {
            "marketplaceId": self.client.marketplace_id,
            "shippingSpeedCategory": "Standard",
            "orderItems": [{"orderItemId": order_item_id, "quantity": quantity}],
            "fulfillmentType": "MFN",
            "shippingInfo": {
                "carrierCode": carrier_code,
                "trackingNumber": tracking_number,
                "shipDateTime": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        }
        await self.client.post(
            f"/orders/v0/orders/{amazon_order_id}/shipmentConfirmation",
            body,
        )
