from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import String, Numeric, ForeignKey, Integer, DateTime, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    sku: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    base_cost: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    weight: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))  # kg
    length: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))  # cm
    width: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    height: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    image_url: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    product_suppliers: Mapped[list["ProductSupplier"]] = relationship(back_populates="product", cascade="all, delete-orphan")
    listings: Mapped[list["MarketplaceListing"]] = relationship(back_populates="product")
    order_line_items: Mapped[list["OrderLineItem"]] = relationship(back_populates="product")


class ProductSupplier(Base):
    """Junction: product <-> supplier with per-supplier cost and stock."""
    __tablename__ = "product_suppliers"
    __table_args__ = (UniqueConstraint("product_id", "supplier_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id", ondelete="CASCADE"))
    supplier_sku: Mapped[str | None] = mapped_column(String(100))
    cost: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    stock: Mapped[int] = mapped_column(Integer, default=0)
    lead_time_days: Mapped[int] = mapped_column(Integer, default=0)
    is_preferred: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    product: Mapped["Product"] = relationship(back_populates="product_suppliers")
    supplier: Mapped["Supplier"] = relationship(back_populates="product_suppliers")
