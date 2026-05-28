from datetime import datetime
from pydantic import BaseModel, ConfigDict
from app.models.marketplace import MarketplaceType, ConnectionStatus, ListingStatus


class ConnectionCreate(BaseModel):
    name: str
    marketplace: MarketplaceType
    credentials: dict = {}
    shop_url: str | None = None
    marketplace_id: str | None = None


class ConnectionUpdate(BaseModel):
    name: str | None = None
    credentials: dict | None = None
    shop_url: str | None = None
    marketplace_id: str | None = None


class ConnectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    marketplace: MarketplaceType
    status: ConnectionStatus
    shop_url: str | None
    marketplace_id: str | None
    last_synced_at: datetime | None
    error_message: str | None
    created_at: datetime
    # Return non-secret credential fields only (client_id, sandbox) so the UI
    # can pre-fill them. Secrets (access_token, client_secret, refresh_token) are stripped.
    client_id: str | None = None
    sandbox: bool = False

    @classmethod
    def model_validate(cls, obj, **kwargs):
        instance = super().model_validate(obj, **kwargs)
        creds = getattr(obj, "credentials", None) or {}
        instance.client_id = creds.get("client_id")
        instance.sandbox = bool(creds.get("sandbox", False))
        return instance


class ListingCreate(BaseModel):
    product_id: int
    connection_id: int
    external_id: str | None = None
    marketplace_sku: str | None = None
    title: str | None = None
    price: float | None = None
    extra_data: dict | None = None


class ListingUpdate(BaseModel):
    product_id: int | None = None
    external_id: str | None = None
    marketplace_sku: str | None = None
    title: str | None = None
    status: ListingStatus | None = None
    price: float | None = None
    extra_data: dict | None = None


class ListingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_id: int | None
    connection_id: int
    external_id: str | None
    marketplace_sku: str | None
    title: str | None
    status: ListingStatus
    price: float | None
    synced_at: datetime | None
    created_at: datetime
    product_name: str | None = None
    product_sku: str | None = None


class PushListingRequest(BaseModel):
    product_ids: list[int]
    connection_id: int
    price: float | None = None


class SyncResult(BaseModel):
    success: int = 0
    failed: int = 0
    errors: list[str] = []


class AutoMapResult(BaseModel):
    mapped: int = 0
    unmatched: list[str] = []
