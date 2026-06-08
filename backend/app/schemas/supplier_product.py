from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict


class SupplierProductCreate(BaseModel):
    name: str
    sku: str
    unit_price: Decimal = Decimal("0")
    stock_quantity: int = 0
    short_name: str | None = None
    weight: Decimal | None = None
    length: Decimal | None = None
    width: Decimal | None = None
    height: Decimal | None = None
    image_url: str | None = None


class SupplierProductUpdate(BaseModel):
    name: str | None = None
    sku: str | None = None
    unit_price: Decimal | None = None
    stock_quantity: int | None = None
    short_name: str | None = None
    weight: Decimal | None = None
    length: Decimal | None = None
    width: Decimal | None = None
    height: Decimal | None = None
    image_url: str | None = None


class SupplierProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    supplier_id: int
    name: str
    sku: str
    unit_price: Decimal
    stock_quantity: int
    short_name: str | None = None
    pending_quantity: int = 0
    sold_quantity: int = 0
    weight: Decimal | None = None
    length: Decimal | None = None
    width: Decimal | None = None
    height: Decimal | None = None
    image_url: str | None = None
    created_at: datetime
    updated_at: datetime
