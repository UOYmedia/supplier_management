from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import Date, DateTime, Float, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    qty_ordered: Mapped[int] = mapped_column(Integer, nullable=False)
    # Supplier-confirmed available stock; may differ from qty_ordered
    qty_available: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    po_number: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
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
