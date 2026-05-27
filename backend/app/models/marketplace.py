from datetime import datetime, timezone
from sqlalchemy import String, ForeignKey, DateTime, Text, Enum as SAEnum, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
import enum


class MarketplaceType(str, enum.Enum):
    amazon = "amazon"
    shopify = "shopify"


class ConnectionStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"
    error = "error"


class ListingStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    inactive = "inactive"
    syncing = "syncing"
    error = "error"


class MarketplaceConnection(Base):
    __tablename__ = "marketplace_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    marketplace: Mapped[MarketplaceType] = mapped_column(SAEnum(MarketplaceType))
    status: Mapped[ConnectionStatus] = mapped_column(SAEnum(ConnectionStatus), default=ConnectionStatus.inactive)
    credentials: Mapped[dict | None] = mapped_column(JSON)  # encrypted at app layer
    shop_url: Mapped[str | None] = mapped_column(String(255))  # for Shopify
    marketplace_id: Mapped[str | None] = mapped_column(String(100))  # Amazon marketplace ID
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    listings: Mapped[list["MarketplaceListing"]] = relationship(back_populates="connection", cascade="all, delete-orphan")


class MarketplaceListing(Base):
    __tablename__ = "marketplace_listings"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    connection_id: Mapped[int] = mapped_column(ForeignKey("marketplace_connections.id", ondelete="CASCADE"))
    external_id: Mapped[str | None] = mapped_column(String(255), index=True)  # ASIN or Shopify product/variant ID
    marketplace_sku: Mapped[str | None] = mapped_column(String(100))
    title: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[ListingStatus] = mapped_column(SAEnum(ListingStatus), default=ListingStatus.draft)
    price: Mapped[float | None] = mapped_column()
    extra_data: Mapped[dict | None] = mapped_column(JSON)  # marketplace-specific fields
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    product: Mapped["Product | None"] = relationship(back_populates="listings")
    connection: Mapped["MarketplaceConnection"] = relationship(back_populates="listings")
