import httpx
from urllib.parse import urljoin


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
