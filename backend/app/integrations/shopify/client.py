import httpx
import re
from urllib.parse import urljoin


def extract_next_page_info(link_header: str | None) -> str | None:
    """Parse Shopify cursor from a Link response header.

    Header format:
        Link: <https://.../products.json?page_info=XYZ&limit=250>; rel="next"
    """
    if not link_header:
        return None
    for part in link_header.split(","):
        if 'rel="next"' in part:
            m = re.search(r"page_info=([^&>]+)", part)
            if m:
                return m.group(1)
    return None


class ShopifyClient:
    """Shopify Admin REST API client."""

    def __init__(self, shop_url: str, access_token: str, api_version: str = "2024-10"):
        self.shop_url = shop_url.rstrip("/")
        self.access_token = access_token
        self.api_version = api_version
        self._base = f"{self.shop_url}/admin/api/{api_version}"

    def _headers(self) -> dict:
        return {"X-Shopify-Access-Token": self.access_token, "Content-Type": "application/json"}

    async def get(self, path: str, params: dict | None = None) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self._base}{path}", headers=self._headers(), params=params)
            resp.raise_for_status()
            return resp.json()

    async def get_with_headers(self, path: str, params: dict | None = None) -> tuple[dict, httpx.Headers]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self._base}{path}", headers=self._headers(), params=params)
            resp.raise_for_status()
            return resp.json(), resp.headers

    async def post(self, path: str, body: dict) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self._base}{path}", headers=self._headers(), json=body)
            resp.raise_for_status()
            return resp.json()

    async def put(self, path: str, body: dict) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.put(f"{self._base}{path}", headers=self._headers(), json=body)
            resp.raise_for_status()
            return resp.json()

    async def get_locations(self) -> list[dict]:
        data = await self.get("/locations.json")
        return data.get("locations", [])

    async def get_fulfillment_orders(self, order_id: str) -> list[dict]:
        data = await self.get(f"/orders/{order_id}/fulfillment_orders.json")
        return data.get("fulfillment_orders", [])
