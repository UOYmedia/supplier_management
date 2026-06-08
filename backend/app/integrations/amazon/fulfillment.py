from datetime import datetime, timezone
from app.integrations.amazon.client import AmazonSPClient


async def confirm_shipment(
    client: AmazonSPClient,
    amazon_order_id: str,
    order_items: list[dict],
    tracking_number: str,
    carrier_code: str = "USPS",
    ship_date: str | None = None,
) -> dict:
    """Confirm shipment for an Amazon order via SP-API.

    order_items: list of {"order_item_id": str, "quantity": int}
    carrier_code: Amazon carrier code string e.g. "USPS", "UPS", "FedEx", "DHL"
    """
    ship_date = ship_date or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = {
        "marketplaceId": client.marketplace_id,
        "packageDetail": {
            "packageReferenceId": "1",
            "carrierCode": carrier_code,
            "trackingNumber": tracking_number,
            "shipDate": ship_date,
            "orderItems": [
                {"orderItemId": item["order_item_id"], "quantity": item["quantity"]}
                for item in order_items
            ],
        },
    }
    return await client.post(
        f"/orders/v0/orders/{amazon_order_id}/shipmentConfirmation",
        body,
    )
