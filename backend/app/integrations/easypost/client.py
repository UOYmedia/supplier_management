"""Async EasyPost REST client (httpx).
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

    @staticmethod
    def _extract_error(r) -> str:
        try:
            body = r.json()
            err = body.get("error", {})
            if isinstance(err, dict):
                return err.get("message") or err.get("code") or r.text
            if isinstance(err, str) and err:
                return err
        except Exception:
            pass
        return r.text or f"HTTP {r.status_code}"

    async def _post(self, path: str, payload: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=30) as http:
                r = await http.post(f"{EASYPOST_BASE}{path}", json=payload, auth=self._auth)
        except httpx.HTTPError as e:
            raise EasyPostError(503, f"EasyPost unreachable: {e}")
        if not r.is_success:
            raise EasyPostError(r.status_code, self._extract_error(r))
        return r.json()

    async def _get(self, path: str, params: dict | None = None) -> dict:
        try:
            async with httpx.AsyncClient(timeout=30) as http:
                r = await http.get(f"{EASYPOST_BASE}{path}", params=params, auth=self._auth)
        except httpx.HTTPError as e:
            raise EasyPostError(503, f"EasyPost unreachable: {e}")
        if not r.is_success:
            raise EasyPostError(r.status_code, self._extract_error(r))
        return r.json()

    async def fetch_label_pdf_b64(self, shipment: dict) -> str | None:
        """Download the EasyPost PNG label and return raw PNG bytes as base64.

        Using PNG avoids EasyPost's PDF formatting quirks (letter-size wrappers,
        misaligned content). Callers build the final PDF with build_label_from_png.
        Only uses label_png_url -- if the shipment was created with PDF format,
        label_png_url won't be present and we return None so callers can call
        regenerate_label() to explicitly request a PNG conversion.
        """
        pl = shipment.get("postage_label") or {}
        png_url = pl.get("label_png_url")
        if not png_url:
            return None
        try:
            async with httpx.AsyncClient(timeout=30) as http:
                r = await http.get(png_url)
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

    async def get_shipment(self, shipment_id: str) -> dict:
        """Retrieve an existing shipment (including already-bought ones)."""
        return await self._get(f"/shipments/{shipment_id}")

    async def regenerate_label(
        self, shipment_id: str, label_size: str = "4x6"
    ) -> tuple[str | None, str | None]:
        """Re-fetch the PNG label for a bought shipment. Returns (png_b64, label_url).

        Raw PNG bytes are returned as base64; callers build the final PDF with
        build_label_from_png so the catalog overlay is applied correctly.
        """
        converted = await self._get(
            f"/shipments/{shipment_id}/label",
            params={"file_format": "png", "label_size": label_size},
        )
        pl = converted.get("postage_label") or {}
        # Only use the explicit PNG URL — label_url may still point to a PDF even
        # when file_format=png is requested (EasyPost doesn't always regenerate).
        png_url = pl.get("label_png_url")
        # label_url (PDF or otherwise) is still useful for the ShippingLabel.label_url field.
        any_url = pl.get("label_url") or png_url
        if not png_url:
            return None, any_url
        try:
            async with httpx.AsyncClient(timeout=30) as http:
                r = await http.get(png_url)
                if not r.is_success:
                    return None, any_url
            # Validate PNG magic bytes so we never pass PDF bytes to ImageReader
            if r.content[:8] != b'\x89PNG\r\n\x1a\n':
                return None, any_url
            return base64.b64encode(r.content).decode(), png_url
        except Exception:
            return None, any_url

    async def list_webhooks(self) -> list[dict]:
        """Return all registered EasyPost webhooks for this account."""
        data = await self._get("/webhooks")
        return data.get("webhooks", [])

    async def create_webhook(self, url: str, webhook_secret: str = "") -> dict:
        """Register a webhook URL with EasyPost. Returns the created webhook object."""
        payload: dict = {"webhook": {"url": url}}
        if webhook_secret:
            payload["webhook"]["webhook_secret"] = webhook_secret
        return await self._post("/webhooks", payload)

    async def create_tracker(self, tracking_code: str, carrier: str = "USPS") -> dict:
        """Create (or look up existing) EasyPost tracker. Returns tracker with .status field.
        Statuses: unknown, pre_transit, in_transit, out_for_delivery, delivered, etc."""
        return await self._post("/trackers", {
            "tracker": {"tracking_code": tracking_code, "carrier": carrier}
        })

    async def refund_shipment(self, shipment_id: str) -> dict:
        """Request a postage refund for a purchased shipment.
        EasyPost returns a refund object; status is typically 'submitted' initially."""
        return await self._post(f"/shipments/{shipment_id}/refunds", {})


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
