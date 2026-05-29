from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict


class SupplierProductCreate(BaseModel):
    name: str
    sku: str
    unit_price: Decimal = Decimal("0")
    stock_quantity: int = 0
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
    sold_quantity: int = 0
    pending_quantity: int = 0
    weight: Decimal | None = None
    length: Decimal | None = None
    width: Decimal | None = None
    height: Decimal | None = None
    image_url: str | None = None
    created_at: datetime
    updated_at: datetime


class ProductComponentCreate(BaseModel):
    supplier_product_id: int
    quantity: int = 1


class ProductComponentUpdate(BaseModel):
    quantity: int


class ProductComponentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_id: int
    supplier_product_id: int
    quantity: int
    supplier_product_name: str | None = None
    supplier_product_sku: str | None = None
    supplier_id: int | None = None
    supplier_name: str | None = None
    unit_price: Decimal | None = None
