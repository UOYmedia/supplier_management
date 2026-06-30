from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ScanLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: str | None
    status: str
    order_status: str | None
    error: str | None
    filled: list | None
    address: dict | None
    created_at: datetime
