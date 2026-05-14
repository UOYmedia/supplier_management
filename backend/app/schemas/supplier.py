from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict
from app.models.supplier import InvoiceStatus


class SupplierBase(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    city: str | None = None
    country: str | None = None
    notes: str | None = None
    is_active: bool = True


class SupplierCreate(SupplierBase):
    pass


class SupplierUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    city: str | None = None
    country: str | None = None
    notes: str | None = None
    is_active: bool | None = None


class SupplierOut(SupplierBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


class SupplierListOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str | None
    city: str | None
    country: str | None
    is_active: bool
    product_count: int = 0
    total_stock: int = 0


class InvoiceLineItemCreate(BaseModel):
    order_line_item_id: int | None = None
    description: str
    quantity: int = 1
    unit_amount: Decimal
    total_amount: Decimal


class InvoiceCreate(BaseModel):
    supplier_id: int
    period_start: datetime
    period_end: datetime
    notes: str | None = None
    line_items: list[InvoiceLineItemCreate] = []


class InvoiceUpdate(BaseModel):
    status: InvoiceStatus | None = None
    notes: str | None = None
    paid_at: datetime | None = None


class InvoiceLineItemOut(InvoiceLineItemCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    invoice_id: int


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    supplier_id: int
    invoice_number: str
    period_start: datetime
    period_end: datetime
    total_amount: Decimal
    status: InvoiceStatus
    notes: str | None
    paid_at: datetime | None
    created_at: datetime
    line_items: list[InvoiceLineItemOut] = []
