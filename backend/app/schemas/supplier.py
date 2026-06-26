from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict
from app.models.supplier import InvoiceStatus


class SupplierBase(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None
    street1: str | None = None
    street2: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    zipcode: str | None = None
    notes: str | None = None
    is_active: bool = True


class SupplierCreate(SupplierBase):
    username: str | None = None
    password: str | None = None


class SupplierUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    street1: str | None = None
    street2: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    zipcode: str | None = None
    notes: str | None = None
    is_active: bool | None = None
    username: str | None = None
    password: str | None = None


class SupplierOut(SupplierBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str | None = None
    created_at: datetime


class SupplierListOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str | None
    phone: str | None
    city: str | None
    state: str | None
    country: str | None
    zipcode: str | None
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


class InvoicePreviewItem(BaseModel):
    order_line_item_id: int
    order_id: int
    order_external_id: str | None = None
    product_name: str
    sku: str | None = None
    quantity: int
    unit_cost: Decimal
    total_cost: Decimal
    fulfill_status: str
    fulfilled_at: datetime | None = None


class InvoicePreviewResponse(BaseModel):
    items: list[InvoicePreviewItem]
    total_amount: Decimal


class InvoiceFromOrdersItem(BaseModel):
    order_line_item_id: int
    description: str
    quantity: int
    unit_amount: Decimal
    total_amount: Decimal


class InvoiceFromOrdersCreate(BaseModel):
    items: list[InvoiceFromOrdersItem]
    notes: str | None = None
