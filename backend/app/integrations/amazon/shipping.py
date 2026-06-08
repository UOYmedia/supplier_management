"""Amazon Merchant Fulfillment API (MFN) — buy shipping labels for seller-fulfilled orders."""
from app.integrations.amazon.client import AmazonSPClient
from app.models.supplier import Supplier


class AmazonMFNShipping:
    """Wraps SP-API /mfn/v0 endpoints for getting rates and purchasing labels."""

    def __init__(self, client: AmazonSPClient):
        self.client = client

    @staticmethod
    def _build_request_details(
        amazon_order_id: str,
        order_items: list[dict],      # [{"OrderItemId": ..., "Quantity": ...}]
        supplier: Supplier,
        parcel: dict,                  # weight_oz, length_in, width_in, height_in
    ) -> dict:
        return {
            "ShipmentRequestDetails": {
                "AmazonOrderId": amazon_order_id,
                "ItemList": [
                    {"OrderItemId": item["OrderItemId"], "Quantity": item["Quantity"]}
                    for item in order_items
                ],
                "ShipFromAddress": {
                    "Name": supplier.name,
                    "AddressLine1": supplier.street1 or "",
                    "AddressLine2": supplier.street2 or "",
                    "City": supplier.city or "",
                    "StateOrRegion": supplier.state or "",
                    "PostalCode": supplier.zipcode or "",
                    "CountryCode": supplier.country or "US",
                    "Phone": supplier.phone or "",
                },
                "PackageDimensions": {
                    "Length": parcel.get("length"),
                    "Width": parcel.get("width"),
                    "Height": parcel.get("height"),
                    "Unit": "inches",
                },
                "Weight": {
                    "Value": parcel.get("weight"),
                    "Unit": "oz",
                },
                "ShippingServiceOptions": {
                    "DeliveryExperience": "DeliveryConfirmationWithoutSignature",
                    "CarrierWillPickUp": False,
                    "LabelFormat": "PDF",
                },
            }
        }

    async def get_eligible_services(
        self,
        amazon_order_id: str,
        order_items: list[dict],
        supplier: Supplier,
        parcel: dict,
    ) -> list[dict]:
        """Return list of eligible shipping services with rates."""
        body = self._build_request_details(amazon_order_id, order_items, supplier, parcel)
        data = await self.client.post("/mfn/v0/eligibleShippingServices", body)
        services = data.get("payload", {}).get("ShippingServiceList", [])
        return [
            {
                "shipping_service_id": s.get("ShippingServiceId"),
                "shipping_service_offer_id": s.get("ShippingServiceOfferId"),
                "name": s.get("ShippingServiceName"),
                "carrier": s.get("CarrierName"),
                "rate": float(s.get("Rate", {}).get("Amount", 0)),
                "currency": s.get("Rate", {}).get("CurrencyCode", "USD"),
                "earliest_delivery": s.get("EarliestEstimatedDeliveryDate"),
                "latest_delivery": s.get("LatestEstimatedDeliveryDate"),
                "requires_additional_inputs": s.get("RequiresAdditionalSellerInputs", False),
            }
            for s in services
            if not s.get("RequiresAdditionalSellerInputs", False)
        ]

    async def buy_label(
        self,
        amazon_order_id: str,
        order_items: list[dict],
        supplier: Supplier,
        parcel: dict,
        shipping_service_id: str,
        shipping_service_offer_id: str,
    ) -> dict:
        """Purchase a shipping label. Returns tracking ID, carrier, service, and base64 PDF."""
        body = self._build_request_details(amazon_order_id, order_items, supplier, parcel)
        body["ShippingServiceId"] = shipping_service_id
        body["ShippingServiceOfferId"] = shipping_service_offer_id

        data = await self.client.post("/mfn/v0/shipments", body)
        shipment = data.get("payload", {}).get("Shipment", {})
        service = shipment.get("ShippingService", {})
        label = shipment.get("Label", {})
        file_contents = label.get("FileContents", {})

        return {
            "shipment_id": shipment.get("ShipmentId"),
            "tracking_number": shipment.get("TrackingId"),
            "carrier": service.get("CarrierName", ""),
            "service": service.get("ShippingServiceName", ""),
            "rate": float(service.get("ShippingServiceOptions", {}).get("DeclaredValue", {}).get("Amount", 0)),
            "label_data": file_contents.get("Contents"),   # base64 encoded PDF
            "label_format": file_contents.get("FileType", "application/pdf"),
        }
