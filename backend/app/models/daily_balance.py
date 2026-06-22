from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import Date, Numeric, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class DailyBalance(Base):
    __tablename__ = "daily_balances"
    __table_args__ = (UniqueConstraint("date", name="uq_daily_balance_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    ending_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # Manual deposit ("nạp thêm") recorded for this day; already folded into ending_balance.
    top_up: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
