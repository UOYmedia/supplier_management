import httpx
from datetime import datetime, timezone


class AmazonSPClient:
    """Amazon Selling Partner API client (LWA + SP-API)."""

    LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
    SP_API_BASE = "https://sellingpartnerapi-na.amazon.com"

    def __init__(self, client_id: str, client_secret: str, refresh_token: str, marketplace_id: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.marketplace_id = marketplace_id
        self._access_token: str | None = None
        self._token_expires: datetime | None = None

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
            from datetime import timedelta
            self._token_expires = datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 3600) - 60)

    async def get(self, path: str, params: dict | None = None) -> dict:
        await self._ensure_token()
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.SP_API_BASE}{path}",
                headers={"x-amz-access-token": self._access_token},
                params=params,
            )
            resp.raise_for_status()
            return resp.json()

    async def post(self, path: str, body: dict) -> dict:
        await self._ensure_token()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.SP_API_BASE}{path}",
                headers={"x-amz-access-token": self._access_token, "Content-Type": "application/json"},
                json=body,
            )
            resp.raise_for_status()
            return resp.json()
