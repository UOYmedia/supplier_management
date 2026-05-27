from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import String, Numeric, ForeignKey, DateTime, Text, Enum as SAEnum, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
import enum


class InvoiceStatus(str, enum.Enum):
    pending = "pending"
    sent = "sent"
    paid = "paid"
    overdue = "overdue"


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    street1: Mapped[str | None] = mapped_column(String(255))
    street2: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str | None] = mapped_column(String(100))
    zipcode: Mapped[str | None] = mapped_column(String(20))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=True)
    username: Mapped[str | None] = mapped_column(String(100), unique=True, index=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255))
    shopify_location_id: Mapped[str | None] = mapped_column(String(100), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    product_suppliers: Mapped[list["ProductSupplier"]] = relationship(back_populates="supplier")
    supplier_products: Mapped[list["SupplierProduct"]] = relationship(back_populates="supplier", cascade="all, delete-orphan")
    order_line_items: Mapped[list["OrderLineItem"]] = relationship(back_populates="supplier")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="supplier", cascade="all, delete-orphan")
    shipping_labels: Mapped[list["ShippingLabel"]] = relationship(back_populates="supplier")


class SupplierProduct(Base):
    """Supplier's own product catalog (inventory items)."""
    __tablename__ = "supplier_products"
    __table_args__ = (UniqueConstraint("supplier_id", "sku"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    sku: Mapped[str] = mapped_column(String(100), index=True)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    stock_quantity: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    supplier: Mapped["Supplier"] = relationship(back_populates="supplier_products")
    components: Mapped[list["ProductComponent"]] = relationship(back_populates="supplier_product", cascade="all, delete-orphan")
    fulfillment_items: Mapped[list["OrderFulfillmentItem"]] = relationship(back_populates="supplier_product")


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id", ondelete="CASCADE"))
    invoice_number: Mapped[str] = mapped_column(String(100), unique=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    status: Mapped[InvoiceStatus] = mapped_column(SAEnum(InvoiceStatus), default=InvoiceStatus.pending)
    notes: Mapped[str | None] = mapped_column(Text)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    supplier: Mapped["Supplier"] = relationship(back_populates="invoices")
    line_items: Mapped[list["InvoiceLineItem"]] = relationship(back_populates="invoice", cascade="all, delete-orphan")


class InvoiceLineItem(Base):
    __tablename__ = "invoice_line_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"))
    order_line_item_id: Mapped[int | None] = mapped_column(ForeignKey("order_line_items.id"))
    description: Mapped[str] = mapped_column(String(500))
    quantity: Mapped[int] = mapped_column(default=1)
    unit_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    invoice: Mapped["Invoice"] = relationship(back_populates="line_items")
    order_line_item: Mapped["OrderLineItem | None"] = relationship()
