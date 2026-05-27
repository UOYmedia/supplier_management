from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import String, Numeric, ForeignKey, Integer, DateTime, Text, Enum as SAEnum, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
import enum


class OrderStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    partially_fulfilled = "partially_fulfilled"
    fulfilled = "fulfilled"
    cancelled = "cancelled"
    refunded = "refunded"


class FulfillStatus(str, enum.Enum):
    unfulfilled = "unfulfilled"
    pending = "pending"
    shipped = "shipped"
    delivered = "delivered"
    cancelled = "cancelled"
    returned = "returned"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int | None] = mapped_column(ForeignKey("marketplace_connections.id"))
    marketplace: Mapped[str] = mapped_column(String(50))  # amazon, shopify, manual
    external_order_id: Mapped[str | None] = mapped_column(String(255), index=True)
    buyer_name: Mapped[str | None] = mapped_column(String(255))
    buyer_email: Mapped[str | None] = mapped_column(String(255))
    shipping_address: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[OrderStatus] = mapped_column(SAEnum(OrderStatus), default=OrderStatus.pending)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    notes: Mapped[str | None] = mapped_column(Text)
    ordered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    connection: Mapped["MarketplaceConnection | None"] = relationship()
    line_items: Mapped[list["OrderLineItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderLineItem(Base):
    __tablename__ = "order_line_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    listing_id: Mapped[int | None] = mapped_column(ForeignKey("marketplace_listings.id"))
    external_line_item_id: Mapped[str | None] = mapped_column(String(255))
    product_name: Mapped[str] = mapped_column(String(255))
    sku: Mapped[str | None] = mapped_column(String(100))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))         # selling price
    base_cost: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)  # cost from supplier
    fulfill_status: Mapped[FulfillStatus] = mapped_column(SAEnum(FulfillStatus), default=FulfillStatus.unfulfilled)
    tracking_number: Mapped[str | None] = mapped_column(String(255))
    label_id: Mapped[int | None] = mapped_column(ForeignKey("shipping_labels.id"))
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    order: Mapped["Order"] = relationship(back_populates="line_items")
    product: Mapped["Product | None"] = relationship(back_populates="order_line_items")
    supplier: Mapped["Supplier | None"] = relationship(back_populates="order_line_items")
    listing: Mapped["MarketplaceListing | None"] = relationship()
    label: Mapped["ShippingLabel | None"] = relationship(foreign_keys=[label_id])
    fulfillment_items: Mapped[list["OrderFulfillmentItem"]] = relationship(back_populates="order_line_item", cascade="all, delete-orphan")


class OrderFulfillmentItem(Base):
    """Supplier-side allocation created when an order line item has product components."""
    __tablename__ = "order_fulfillment_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_line_item_id: Mapped[int] = mapped_column(ForeignKey("order_line_items.id", ondelete="CASCADE"))
    supplier_product_id: Mapped[int] = mapped_column(ForeignKey("supplier_products.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    fulfill_status: Mapped[FulfillStatus] = mapped_column(SAEnum(FulfillStatus), default=FulfillStatus.unfulfilled)
    tracking_number: Mapped[str | None] = mapped_column(String(255))
    label_id: Mapped[int | None] = mapped_column(ForeignKey("shipping_labels.id"))
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    order_line_item: Mapped["OrderLineItem"] = relationship(back_populates="fulfillment_items")
    supplier_product: Mapped["SupplierProduct"] = relationship(back_populates="fulfillment_items")
    label: Mapped["ShippingLabel | None"] = relationship(foreign_keys=[label_id])


class ShippingLabel(Base):
    __tablename__ = "shipping_labels"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    carrier: Mapped[str] = mapped_column(String(50))
    service: Mapped[str | None] = mapped_column(String(100))
    tracking_number: Mapped[str | None] = mapped_column(String(255))
    label_url: Mapped[str | None] = mapped_column(String(500))
    cost: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=0)
    from_address: Mapped[dict | None] = mapped_column(JSON)
    to_address: Mapped[dict | None] = mapped_column(JSON)
    purchased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    supplier: Mapped["Supplier"] = relationship(back_populates="shipping_labels")
