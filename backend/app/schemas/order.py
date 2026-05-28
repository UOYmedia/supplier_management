from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict
from app.models.order import OrderStatus, FulfillStatus


class ShippingAddress(BaseModel):
    name: str | None = None
    line1: str | None = None
    line2: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    country: str | None = None
    phone: str | None = None


class OrderLineItemCreate(BaseModel):
    product_id: int | None = None
    supplier_id: int | None = None
    listing_id: int | None = None
    product_name: str
    sku: str | None = None
    quantity: int = 1
    price: Decimal
    base_cost: Decimal = Decimal("0")


class OrderLineItemUpdate(BaseModel):
    supplier_id: int | None = None
    base_cost: Decimal | None = None
    fulfill_status: FulfillStatus | None = None
    tracking_number: str | None = None
    label_id: int | None = None
    fulfilled_at: datetime | None = None


class OrderFulfillmentItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    order_line_item_id: int
    supplier_product_id: int
    quantity: int
    fulfill_status: FulfillStatus
    tracking_number: str | None
    label_id: int | None
    fulfilled_at: datetime | None
    supplier_product_name: str | None = None
    supplier_product_sku: str | None = None
    supplier_id: int | None = None
    supplier_name: str | None = None


class OrderFulfillmentItemUpdate(BaseModel):
    fulfill_status: FulfillStatus | None = None
    tracking_number: str | None = None
    label_id: int | None = None
    fulfilled_at: datetime | None = None


class OrderLineItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    order_id: int
    product_id: int | None
    supplier_id: int | None
    product_name: str
    sku: str | None
    quantity: int
    price: Decimal
    base_cost: Decimal
    fulfill_status: FulfillStatus
    tracking_number: str | None
    label_id: int | None
    fulfilled_at: datetime | None
    supplier_name: str | None = None
    fulfillment_items: list[OrderFulfillmentItemOut] = []


class OrderCreate(BaseModel):
    marketplace: str = "manual"
    buyer_name: str | None = None
    buyer_email: str | None = None
    shipping_address: ShippingAddress | None = None
    currency: str = "USD"
    notes: str | None = None
    line_items: list[OrderLineItemCreate] = []


class OrderUpdate(BaseModel):
    status: OrderStatus | None = None
    notes: str | None = None
    buyer_name: str | None = None
    buyer_email: str | None = None
    shipping_address: ShippingAddress | None = None


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    marketplace: str
    external_order_id: str | None
    buyer_name: str | None
    buyer_email: str | None
    shipping_address: dict | None
    status: OrderStatus
    total: Decimal
    currency: str
    notes: str | None
    ordered_at: datetime
    created_at: datetime
    line_items: list[OrderLineItemOut] = []


class AssignSupplierBody(BaseModel):
    supplier_id: int
    base_cost: Decimal | None = None
    create_product_supplier: bool = True
    is_preferred: bool = False
    supplier_product_id: int | None = None
    units: int = 1


class ShippingLabelCreate(BaseModel):
    supplier_id: int
    carrier: str
    service: str | None = None
    tracking_number: str | None = None
    label_url: str | None = None
    cost: Decimal = Decimal("0")
    from_address: dict | None = None
    to_address: dict | None = None
    line_item_ids: list[int] = []


class ShippingLabelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    supplier_id: int
    carrier: str
    service: str | None
    tracking_number: str | None
    label_url: str | None
    has_label_data: bool = False   # true when Amazon PDF is stored; use /labels/{id}/download
    cost: Decimal
    purchased_at: datetime
