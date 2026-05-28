import httpx
from datetime import datetime, timezone, timedelta


class AmazonAPIError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


class AmazonSPClient:
    """Amazon Selling Partner API client (LWA + SP-API)."""

    LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
    SP_API_BASE_PRODUCTION = "https://sellingpartnerapi-na.amazon.com"
    SP_API_BASE_SANDBOX = "https://sandbox.sellingpartnerapi-na.amazon.com"

    def __init__(self, client_id: str, client_secret: str, refresh_token: str, marketplace_id: str, sandbox: bool = False):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.marketplace_id = marketplace_id
        self.sandbox = sandbox
        self.SP_API_BASE = self.SP_API_BASE_SANDBOX if sandbox else self.SP_API_BASE_PRODUCTION
        self._access_token: str | None = None
        self._token_expires: datetime | None = None
        self._seller_id: str | None = None

    async def _ensure_token(self):
        if self._access_token and self._token_expires and datetime.now(timezone.utc) < self._token_expires:
            return
        async with httpx.AsyncClient() as client:
            resp = await client.post(self.LWA_TOKEN_URL, data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            })
            resp.raise_for_status()
            data = resp.json()
            self._access_token = data["access_token"]
            self._token_expires = datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 3600) - 60)

    async def get(self, path: str, params: dict | None = None) -> dict:
        await self._ensure_token()
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.SP_API_BASE}{path}",
                headers={"x-amz-access-token": self._access_token},
                params=params,
            )
            if not resp.is_success:
                raise AmazonAPIError(resp.status_code, f"Amazon API error {resp.status_code}: {resp.text[:300]}")
            return resp.json()

    async def post(self, path: str, body: dict) -> dict:
        await self._ensure_token()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.SP_API_BASE}{path}",
                headers={"x-amz-access-token": self._access_token, "Content-Type": "application/json"},
                json=body,
            )
            if not resp.is_success:
                raise AmazonAPIError(resp.status_code, f"Amazon API error {resp.status_code}: {resp.text[:300]}")
            return resp.json()

    async def delete(self, path: str) -> dict:
        await self._ensure_token()
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{self.SP_API_BASE}{path}",
                headers={"x-amz-access-token": self._access_token},
            )
            if not resp.is_success:
                raise AmazonAPIError(resp.status_code, f"Amazon API error {resp.status_code}: {resp.text[:300]}")
            return resp.json() if resp.content else {}

    async def get_seller_id(self) -> str:
        """Return cached seller ID, fetching from Participations API if needed."""
        if self._seller_id:
            return self._seller_id
        data = await self.get("/sellers/v1/marketplaceParticipations")
        participations = data.get("payload", [])
        if participations:
            # sellerId is not directly in participations in all API versions;
            # it's tied to the LWA token. Use the first marketplace's seller info.
            self._seller_id = data.get("sellerId") or ""
        return self._seller_id or ""
