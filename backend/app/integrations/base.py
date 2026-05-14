from abc import ABC, abstractmethod
from app.models.marketplace import MarketplaceConnection
from app.models.product import Product


class MarketplaceSyncer(ABC):
    def __init__(self, connection: MarketplaceConnection):
        self.connection = connection
        self.credentials = connection.credentials or {}

    @abstractmethod
    async def test_connection(self) -> bool:
        ...

    @abstractmethod
    async def push_product(self, product: Product, price: float | None = None) -> str:
        """Push product to marketplace and return external_id."""
        ...

    @abstractmethod
    async def sync_orders(self, db) -> int:
        """Pull new orders from marketplace and upsert into DB. Returns count."""
        ...
