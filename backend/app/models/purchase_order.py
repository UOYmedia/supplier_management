from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # Stable link to the supplier row. Stock increment on PAID matches on this id
    # (the `supplier` name is kept for display and as a fallback for old rows).
    supplier_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("suppliers.id"), nullable=True, index=True
    )
    sku: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    qty_ordered: Mapped[int] = mapped_column(Integer, nullable=False)
    # Supplier-confirmed available stock; may differ from qty_ordered
    qty_available: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    po_number: Mapped[str] = mapped_column(String(100), nullable=False, index=True, default="")
    record_type: Mapped[str] = mapped_column(String(10), nullable=False, default="daily", index=True)
    # Groups the line items submitted together in one request (many products,
    # one submit). Each line stays its own row; this ties them for display.
    request_group: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    paid_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    pic: Mapped[str] = mapped_column(String(100), nullable=False)
    amount_paid: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    requested_date: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    approved_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class DailyStockSnapshot(Base):
    """End-of-day frozen snapshot of a supplier's catalog.

    `business_date` is the calendar day in US Pacific time (the timezone Amazon
    uses to record orders), so the numbers line up with the day shown on the
    marketplace. Written by the nightly scheduler job (and re-runnable on
    demand); the daily PO statement PDF for any past date is rendered from these
    rows. `created_at` is stored in UTC.
    """
    __tablename__ = "daily_stock_snapshots"
    __table_args__ = (
        UniqueConstraint("business_date", "supplier_id", "sku", name="uq_snapshot_day_supplier_sku"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    supplier_id: Mapped[int] = mapped_column(Integer, ForeignKey("suppliers.id"), nullable=False, index=True)
    supplier_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sku: Mapped[str] = mapped_column(String(255), nullable=False)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    available: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ordered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    oversold: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Units shipped/delivered as of this day (mirrors the catalog SOLD column).
    sold: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    avail_value: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    oversold_value: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
