"""
Async EasyPost REST client (httpx).
Docs: https://www.easypost.com/docs/api
"""
import httpx
from typing import Any

EASYPOST_BASE = "https://api.easypost.com/v2"


class EasyPostError(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        super().__init__(detail)


class EasyPostClient:
    def __init__(self, api_key: str):
        self._auth = (api_key, "")

    async def _post(self, path: str, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=30) as http:
            r = await http.post(f"{EASYPOST_BASE}{path}", json=payload, auth=self._auth)
        if not r.is_success:
            detail = r.json().get("error", {}).get("message", r.text)
            raise EasyPostError(r.status_code, detail)
        return r.json()

    async def create_shipment(
        self,
        to_address: dict,
        from_address: dict,
        parcel: dict,
        carrier_accounts: list[str] | None = None,
    ) -> dict:
        """Create shipment and return rates. Parcel weight in oz, dims in inches."""
        shipment: dict[str, Any] = {
            "to_address": to_address,
            "from_address": from_address,
            "parcel": parcel,
        }
        if carrier_accounts:
            shipment["carrier_accounts"] = [{"id": ca} for ca in carrier_accounts]
        data = await self._post("/shipments", {"shipment": shipment})
        return data

    async def buy_shipment(self, shipment_id: str, rate_id: str) -> dict:
        """Purchase a rate. Returns the bought shipment with label URL + tracking."""
        return await self._post(f"/shipments/{shipment_id}/buy", {"rate": {"id": rate_id}})


def supplier_to_ep_address(supplier) -> dict:
    """Convert Supplier ORM object to EasyPost address dict."""
    return {
        "name": supplier.name,
        "street1": supplier.street1 or "",
        "street2": supplier.street2 or "",
        "city": supplier.city or "",
        "state": supplier.state or "",
        "zip": supplier.zipcode or "",
        "country": supplier.country or "US",
        "phone": supplier.phone or "",
        "email": supplier.email or "",
    }


def shipping_addr_to_ep(addr: dict) -> dict:
    """Convert our ShippingAddress JSON to EasyPost address dict."""
    return {
        "name": addr.get("name", ""),
        "street1": addr.get("line1", ""),
        "street2": addr.get("line2", ""),
        "city": addr.get("city", ""),
        "state": addr.get("state", ""),
        "zip": addr.get("zip", ""),
        "country": addr.get("country", "US"),
        "phone": addr.get("phone", ""),
    }


def filter_usps_rates(rates: list[dict]) -> list[dict]:
    return [r for r in rates if r.get("carrier", "").upper() == "USPS"]
