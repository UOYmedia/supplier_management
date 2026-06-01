"""
Async EasyPost REST client (httpx).
Docs: https://www.easypost.com/docs/api
"""
import base64
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
        try:
            async with httpx.AsyncClient(timeout=30) as http:
                r = await http.post(f"{EASYPOST_BASE}{path}", json=payload, auth=self._auth)
        except httpx.HTTPError as e:
            raise EasyPostError(503, f"EasyPost unreachable: {e}")
        if not r.is_success:
            try:
                detail = r.json().get("error", {}).get("message", r.text)
            except Exception:
                detail = r.text or f"HTTP {r.status_code}"
            raise EasyPostError(r.status_code, detail)
        return r.json()

    async def _get(self, path: str, params: dict | None = None) -> dict:
        try:
            async with httpx.AsyncClient(timeout=30) as http:
                r = await http.get(f"{EASYPOST_BASE}{path}", params=params, auth=self._auth)
        except httpx.HTTPError as e:
            raise EasyPostError(503, f"EasyPost unreachable: {e}")
        if not r.is_success:
            try:
                detail = r.json().get("error", {}).get("message", r.text)
            except Exception:
                detail = r.text or f"HTTP {r.status_code}"
            raise EasyPostError(r.status_code, detail)
        return r.json()

    async def fetch_label_pdf_b64(self, shipment: dict) -> str | None:
        """Convert a bought shipment's label to 4x6 PDF and download bytes as base64.

        EasyPost labels default to PNG. We re-request format=PDF at 4x6 inches,
        then download the PDF bytes so we can archive and serve same-origin
        (which enables the browser to auto-trigger print).
        """
        shipment_id = shipment.get("id")
        if not shipment_id:
            return None
        pdf_url = None
        try:
            converted = await self._get(
                f"/shipments/{shipment_id}/label",
                params={"file_format": "pdf", "label_size": "4x6"},
            )
            pl = converted.get("postage_label") or {}
            pdf_url = pl.get("label_pdf_url") or pl.get("label_url")
        except Exception:
            pl = shipment.get("postage_label") or {}
            pdf_url = pl.get("label_pdf_url") or pl.get("label_url")
        if not pdf_url:
            return None
        try:
            async with httpx.AsyncClient(timeout=30) as http:
                r = await http.get(pdf_url)
                if not r.is_success:
                    return None
                return base64.b64encode(r.content).decode()
        except Exception:
            return None

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
            "options": {"label_format": "PDF", "label_size": "4x6"},
        }
        if carrier_accounts:
            shipment["carrier_accounts"] = [{"id": ca} for ca in carrier_accounts]
        data = await self._post("/shipments", {"shipment": shipment})
        return data

    async def buy_shipment(self, shipment_id: str, rate_id: str) -> dict:
        """Purchase a rate. Returns the bought shipment with label URL + tracking."""
        return await self._post(f"/shipments/{shipment_id}/buy", {"rate": {"id": rate_id}})

    async def regenerate_label(
        self, shipment_id: str, label_size: str = "4x6"
    ) -> tuple[str | None, str | None]:
        """Re-request a bought shipment's label as a PDF at the given size.

        Returns (label_data_b64, label_url). Used to regenerate a label PDF on
        demand (e.g. to fix a missing archive or change the printed size).
        """
        converted = await self._get(
            f"/shipments/{shipment_id}/label",
            params={"file_format": "pdf", "label_size": label_size},
        )
        pl = converted.get("postage_label") or {}
        pdf_url = pl.get("label_pdf_url") or pl.get("label_url")
        if not pdf_url:
            return None, None
        try:
            async with httpx.AsyncClient(timeout=30) as http:
                r = await http.get(pdf_url)
                if not r.is_success:
                    return None, pdf_url
                return base64.b64encode(r.content).decode(), pdf_url
        except Exception:
            return None, pdf_url

    async def create_tracker(self, tracking_code: str, carrier: str = "USPS") -> dict:
        """Create (or look up existing) EasyPost tracker. Returns tracker with .status field.
        Statuses: unknown, pre_transit, in_transit, out_for_delivery, delivered, etc."""
        return await self._post("/trackers", {
            "tracker": {"tracking_code": tracking_code, "carrier": carrier}
        })


def supplier_to_ep_address(supplier) -> dict:
    """Convert Supplier ORM object to EasyPost address dict."""
    raw_country = supplier.country or "US"
    country = "US" if raw_country.lower() in ("united states", "united states of america", "us") else raw_country
    return {
        "name": supplier.name,
        "street1": supplier.street1 or "",
        "street2": supplier.street2 or "",
        "city": supplier.city or "",
        "state": supplier.state or "",
        "zip": supplier.zipcode or "",
        "country": country,
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


SUPPORTED_CARRIERS = {"USPS", "UPS"}


def filter_usps_rates(rates: list[dict]) -> list[dict]:
    return [r for r in rates if r.get("carrier", "").upper() == "USPS"]


def filter_supported_rates(rates: list[dict]) -> list[dict]:
    """Return USPS + UPS rates; falls back to all rates if neither is present."""
    filtered = [r for r in rates if r.get("carrier", "").upper() in SUPPORTED_CARRIERS]
    return filtered or rates
