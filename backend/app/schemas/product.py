from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict


class ProductSupplierBase(BaseModel):
    supplier_id: int
    supplier_sku: str | None = None
    cost: Decimal = Decimal("0")
    stock: int = 0
    lead_time_days: int = 0
    is_preferred: bool = False


class ProductSupplierCreate(ProductSupplierBase):
    supplier_product_id: int | None = None
    units: int = 1


class ProductSupplierUpdate(BaseModel):
    supplier_sku: str | None = None
    cost: Decimal | None = None
    stock: int | None = None
    lead_time_days: int | None = None
    is_preferred: bool | None = None


class ProductSupplierOut(ProductSupplierBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_id: int
    updated_at: datetime
    supplier_name: str | None = None


class ProductBase(BaseModel):
    name: str
    sku: str
    description: str | None = None
    base_cost: Decimal = Decimal("0")
    weight: Decimal | None = None
    length: Decimal | None = None
    width: Decimal | None = None
    height: Decimal | None = None
    image_url: str | None = None
    is_active: bool = True


class ProductCreate(ProductBase):
    suppliers: list[ProductSupplierCreate] = []


class ProductUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    base_cost: Decimal | None = None
    weight: Decimal | None = None
    length: Decimal | None = None
    width: Decimal | None = None
    height: Decimal | None = None
    image_url: str | None = None
    is_active: bool | None = None


class ProductOut(ProductBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime
    product_suppliers: list[ProductSupplierOut] = []


class ProductListOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    sku: str
    base_cost: Decimal
    is_active: bool
    supplier_count: int = 0
    total_stock: int = 0


class ProductImportRow(BaseModel):
    name: str
    sku: str
    base_cost: Decimal = Decimal("0")
    weight: Decimal | None = None
    length: Decimal | None = None
    width: Decimal | None = None
    height: Decimal | None = None
    description: str | None = None
