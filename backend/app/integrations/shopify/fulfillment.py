from app.integrations.shopify.client import ShopifyClient


class ShopifyFulfillment:
    def __init__(self, client: ShopifyClient):
        self.client = client

    async def create_fulfillment(
        self,
        shopify_order_id: str,
        line_item_id: str,
        tracking_number: str,
        carrier: str,
        location_id: int | None = None,
        notify_customer: bool = True,
    ) -> dict:
        """Create a fulfillment record on Shopify with a tracking number."""
        body: dict = {
            "fulfillment": {
                "tracking_number": tracking_number,
                "tracking_company": carrier,
                "notify_customer": notify_customer,
                "line_items": [{"id": int(line_item_id)}],
            }
        }
        if location_id:
            body["fulfillment"]["location_id"] = location_id
        result = await self.client.post(
            f"/orders/{shopify_order_id}/fulfillments.json",
            body,
        )
        return result.get("fulfillment", {})
