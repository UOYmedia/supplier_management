import httpx
from urllib.parse import urlparse, parse_qs


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
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{self._base}{path}", headers=self._headers(), params=params)
            resp.raise_for_status()
            return resp.json()

    async def get_with_headers(self, path: str, params: dict | None = None) -> tuple[dict, dict]:
        """Like get() but also returns the response headers (needed for Link pagination)."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{self._base}{path}", headers=self._headers(), params=params)
            resp.raise_for_status()
            return resp.json(), dict(resp.headers)

    async def post(self, path: str, body: dict) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{self._base}{path}", headers=self._headers(), json=body)
            resp.raise_for_status()
            return resp.json()

    async def put(self, path: str, body: dict) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.put(f"{self._base}{path}", headers=self._headers(), json=body)
            resp.raise_for_status()
            return resp.json()

    async def get_locations(self) -> list[dict]:
        data = await self.get("/locations.json")
        return data.get("locations", [])

    async def get_fulfillment_orders(self, order_id: str) -> list[dict]:
        data = await self.get(f"/orders/{order_id}/fulfillment_orders.json")
        return data.get("fulfillment_orders", [])


def extract_next_page_info(link_header: str | None) -> str | None:
    """Parse Shopify Link header and return the next page_info cursor, or None."""
    if not link_header:
        return None
    for part in link_header.split(","):
        part = part.strip()
        if 'rel="next"' in part:
            url_part = part.split(";")[0].strip()
            if url_part.startswith("<") and url_part.endswith(">"):
                parsed = urlparse(url_part[1:-1])
                page_info_list = parse_qs(parsed.query).get("page_info", [])
                if page_info_list:
                    return page_info_list[0]
    return None
