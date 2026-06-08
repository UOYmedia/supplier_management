import httpx
from datetime import datetime, timezone


class AmazonAPIError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


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

    async def get(self, path: str, params: dict | None = None, rdt: str | None = None) -> dict:
        await self._ensure_token()
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.SP_API_BASE}{path}",
                headers={"x-amz-access-token": rdt or self._access_token},
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

    async def create_restricted_data_token(
        self,
        path: str,
        method: str = "GET",
        data_elements: list[str] | None = None,
    ) -> str | None:
        """Request a Restricted Data Token so PII endpoints
        (/orders/{id}/address, /orders/{id}/buyerInfo) can be called.

        Returns the token, or None if the seller account isn't authorised for
        the requested data elements (Amazon returns 403/Unauthorized — common
        for sellers without the PII data role)."""
        body = {
            "restrictedResources": [
                {
                    "method": method,
                    "path": path,
                    **({"dataElements": data_elements} if data_elements else {}),
                }
            ]
        }
        try:
            data = await self.post("/tokens/2021-03-03/restrictedDataToken", body)
            return data.get("restrictedDataToken")
        except AmazonAPIError as e:
            print(f"Amazon RDT denied for {path}: {e}", flush=True)
            return None
