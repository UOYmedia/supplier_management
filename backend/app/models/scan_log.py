from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class ScanLog(Base):
    """Audit log for every shipping-label scan attempt (success or failure)."""
    __tablename__ = "scan_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Amazon external order id (the PNG filename); may not map to a real order.
    order_id: Mapped[str | None] = mapped_column(String(100), index=True)
    # updated | already_has_address | not_found | scan_failed | no_api_key | ...
    status: Mapped[str] = mapped_column(String(30), index=True)
    error: Mapped[str | None] = mapped_column(Text)
    filled: Mapped[list | None] = mapped_column(JSON)   # address fields filled in
    address: Mapped[dict | None] = mapped_column(JSON)  # parsed / merged address
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
